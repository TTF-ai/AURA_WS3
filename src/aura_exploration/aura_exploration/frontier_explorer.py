import math
from enum import Enum

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from tf2_ros import Buffer, TransformException, TransformListener


class ExplorerState(Enum):
    SEARCH_FRONTIER = 1
    SEND_GOAL = 2
    WAIT_FOR_RESULT = 3


class FrontierExplorer(Node):
    def __init__(self):
        super().__init__('frontier_explorer')

        self.declare_parameter('map_topic', '/map')
        self.declare_parameter('min_frontier_size', 5)
        self.declare_parameter('min_frontier_distance', 0.5)
        self.declare_parameter('max_frontier_distance', 5.0)
        self.declare_parameter('goal_tolerance', 0.4)
        self.declare_parameter('exploration_period', 1.0)
        self.declare_parameter('map_frame', 'map')
        self.declare_parameter('base_frame', 'base_link')

        self.map_topic = self.get_parameter('map_topic').value
        self.min_frontier_size = int(self.get_parameter('min_frontier_size').value)
        self.min_frontier_distance = float(
            self.get_parameter('min_frontier_distance').value)
        self.max_frontier_distance = float(
            self.get_parameter('max_frontier_distance').value)
        self.goal_tolerance = float(self.get_parameter('goal_tolerance').value)
        self.map_frame = self.get_parameter('map_frame').value
        self.base_frame = self.get_parameter('base_frame').value

        self.latest_map = None
        self.state = ExplorerState.SEARCH_FRONTIER
        self.current_goal_handle = None
        self.current_goal = None
        self.blacklisted_goals = []
        self.completion_logged = False

        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        self.action_client = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.map_subscription = self.create_subscription(
            OccupancyGrid,
            self.map_topic,
            self.map_callback,
            10,
        )
        self.timer = self.create_timer(
            float(self.get_parameter('exploration_period').value),
            self.exploration_step,
        )

        self.get_logger().info('Frontier explorer started')

    def map_callback(self, map_message):
        if not self._valid_map(map_message):
            self.get_logger().warning('Ignoring invalid or empty occupancy grid')
            return
        self.latest_map = map_message
        self.completion_logged = False

    def exploration_step(self):
        if self.state != ExplorerState.SEARCH_FRONTIER or self.latest_map is None:
            return

        robot_pose = self._robot_pose(self.latest_map.header.frame_id)
        if robot_pose is None:
            return

        frontier_goal = self._select_frontier(self.latest_map, robot_pose)
        if frontier_goal is None:
            if not self.completion_logged:
                self.get_logger().info(
                    'Exploration complete: no valid frontiers.')
                self.completion_logged = True
            return

        self.current_goal = frontier_goal
        self.state = ExplorerState.SEND_GOAL
        frame_id = self.latest_map.header.frame_id or self.map_frame
        self._send_goal(frontier_goal, frame_id)

    def _send_goal(self, goal, frame_id):
        if not self.action_client.server_is_ready():
            self.get_logger().warning('Nav2 NavigateToPose action server is not ready')
            self.state = ExplorerState.SEARCH_FRONTIER
            return

        goal_message = NavigateToPose.Goal()
        goal_message.pose = PoseStamped()
        goal_message.pose.header.frame_id = frame_id
        goal_message.pose.header.stamp = self.get_clock().now().to_msg()
        goal_message.pose.pose.position.x = goal[0]
        goal_message.pose.pose.position.y = goal[1]
        goal_message.pose.pose.orientation = goal[2]

        send_future = self.action_client.send_goal_async(goal_message)
        send_future.add_done_callback(self._goal_response_callback)
        self.get_logger().info(
            'Sending frontier goal (%.2f, %.2f)' % (goal[0], goal[1]))

    def _goal_response_callback(self, future):
        try:
            goal_handle = future.result()
        except Exception as error:
            self.get_logger().error('Failed to send navigation goal: %s' % error)
            self._blacklist_current_goal()
            return

        if not goal_handle.accepted:
            self.get_logger().warning('Nav2 rejected frontier goal')
            self._blacklist_current_goal()
            return

        self.current_goal_handle = goal_handle
        self.state = ExplorerState.WAIT_FOR_RESULT
        result_future = goal_handle.get_result_async()
        result_future.add_done_callback(self._goal_result_callback)

    def _goal_result_callback(self, future):
        try:
            result = future.result()
            status = result.status
        except Exception as error:
            self.get_logger().error('Navigation result failed: %s' % error)
            self._blacklist_current_goal()
            return

        if status == GoalStatus.STATUS_SUCCEEDED:
            self.get_logger().info('Frontier goal reached')
        else:
            self.get_logger().warning(
                'Frontier goal failed with Nav2 status %d; blacklisting it' % status)
            self._blacklist_current_goal()

        self.current_goal_handle = None
        self.current_goal = None
        self.state = ExplorerState.SEARCH_FRONTIER

    def _select_frontier(self, map_message, robot_pose):
        frontiers = self._find_frontier_clusters(map_message)
        candidates = []
        for cluster in frontiers:
            if len(cluster) < self.min_frontier_size:
                continue

            goal_x, goal_y = self._cluster_centroid(map_message, cluster)
            distance = math.hypot(
                goal_x - robot_pose[0], goal_y - robot_pose[1])
            if distance < self.min_frontier_distance:
                continue
            if distance > self.max_frontier_distance:
                continue
            if self._blacklisted(goal_x, goal_y):
                continue
            if not self._goal_cell_is_free(map_message, goal_x, goal_y):
                continue

            candidates.append((distance, goal_x, goal_y))

        if not candidates:
            return None

        _, goal_x, goal_y = min(candidates, key=lambda candidate: candidate[0])
        return goal_x, goal_y, robot_pose[2]

    def _find_frontier_clusters(self, map_message):
        width = map_message.info.width
        height = map_message.info.height
        data = map_message.data
        frontier_cells = set()

        for row in range(height):
            for column in range(width):
                index = row * width + column
                if data[index] != 0:
                    continue
                for neighbor_row, neighbor_column in self._neighbors(
                        row, column, width, height):
                    if data[neighbor_row * width + neighbor_column] == -1:
                        frontier_cells.add((row, column))
                        break

        clusters = []
        while frontier_cells:
            seed = frontier_cells.pop()
            cluster = [seed]
            pending = [seed]
            while pending:
                cell = pending.pop()
                for neighbor in self._neighbors(
                        cell[0], cell[1], width, height):
                    if neighbor in frontier_cells:
                        frontier_cells.remove(neighbor)
                        pending.append(neighbor)
                        cluster.append(neighbor)
            clusters.append(cluster)

        return clusters

    @staticmethod
    def _neighbors(row, column, width, height):
        for row_offset in (-1, 0, 1):
            for column_offset in (-1, 0, 1):
                if row_offset == 0 and column_offset == 0:
                    continue
                neighbor_row = row + row_offset
                neighbor_column = column + column_offset
                if 0 <= neighbor_row < height and 0 <= neighbor_column < width:
                    yield neighbor_row, neighbor_column

    def _cluster_centroid(self, map_message, cluster):
        origin = map_message.info.origin
        resolution = map_message.info.resolution
        origin_yaw = self._yaw_from_quaternion(origin.orientation)
        centroid_column = sum(cell[1] + 0.5 for cell in cluster) / len(cluster)
        centroid_row = sum(cell[0] + 0.5 for cell in cluster) / len(cluster)
        local_x = centroid_column * resolution
        local_y = centroid_row * resolution
        return self._local_to_world(origin, origin_yaw, local_x, local_y)

    def _goal_cell_is_free(self, map_message, world_x, world_y):
        cell = self._world_to_cell(map_message, world_x, world_y)
        if cell is None:
            return False
        row, column = cell
        index = row * map_message.info.width + column
        return map_message.data[index] == 0

    def _world_to_cell(self, map_message, world_x, world_y):
        origin = map_message.info.origin
        resolution = map_message.info.resolution
        if resolution <= 0.0:
            return None
        origin_yaw = self._yaw_from_quaternion(origin.orientation)
        delta_x = world_x - origin.position.x
        delta_y = world_y - origin.position.y
        local_x = math.cos(origin_yaw) * delta_x + math.sin(origin_yaw) * delta_y
        local_y = -math.sin(origin_yaw) * delta_x + math.cos(origin_yaw) * delta_y
        column = math.floor(local_x / resolution)
        row = math.floor(local_y / resolution)
        if not (0 <= row < map_message.info.height and
                0 <= column < map_message.info.width):
            return None
        return row, column

    @staticmethod
    def _local_to_world(origin, origin_yaw, local_x, local_y):
        return (
            origin.position.x + math.cos(origin_yaw) * local_x -
            math.sin(origin_yaw) * local_y,
            origin.position.y + math.sin(origin_yaw) * local_x +
            math.cos(origin_yaw) * local_y,
        )

    def _robot_pose(self, frame_id):
        try:
            transform = self.tf_buffer.lookup_transform(
                frame_id or self.map_frame,
                self.base_frame,
                rclpy.time.Time(),
            )
        except TransformException as error:
            self.get_logger().warning('Waiting for robot pose in map frame: %s' % error)
            return None

        translation = transform.transform.translation
        rotation = transform.transform.rotation
        return translation.x, translation.y, rotation

    def _blacklisted(self, world_x, world_y):
        return any(
            math.hypot(world_x - goal_x, world_y - goal_y) <= self.goal_tolerance
            for goal_x, goal_y in self.blacklisted_goals)

    def _blacklist_current_goal(self):
        if self.current_goal is not None:
            self.blacklisted_goals.append(self.current_goal[:2])
        self.current_goal_handle = None
        self.current_goal = None
        self.state = ExplorerState.SEARCH_FRONTIER

    @staticmethod
    def _valid_map(map_message):
        return (
            map_message.info.width > 0 and
            map_message.info.height > 0 and
            map_message.info.resolution > 0.0 and
            len(map_message.data) >= map_message.info.width * map_message.info.height)

    @staticmethod
    def _yaw_from_quaternion(quaternion):
        return math.atan2(
            2.0 * (quaternion.w * quaternion.z + quaternion.x * quaternion.y),
            1.0 - 2.0 * (quaternion.y * quaternion.y + quaternion.z * quaternion.z),
        )

    def destroy_node(self):
        if self.current_goal_handle is not None:
            self.current_goal_handle.cancel_goal_async()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = FrontierExplorer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()