# AURA startup scripts

## Correct architecture

The physical OV5647 camera is connected to the Raspberry Pi 5, and the existing `camera_node` inside `aura_face_auth` is the correct source of `/camera/image_raw`.

### Raspberry Pi 5
The Pi runs the physical camera publisher and robot stack:

- `ros2 launch aura_bringup robot.launch.py`
- `ros2 run aura_face_auth camera_node --ros-args -p camera_index:=0 -p frame_width:=640 -p frame_height:=480 -p fps:=30`
- `ros2 launch aura_slam slam.launch.py`
- `ros2 launch aura_navigation navigation.launch.py map:=/absolute/path/to/map.yaml use_rviz:=false`
- `ros2 launch aura_exploration exploration.launch.py`

### Laptop
The laptop only runs the AI and behavior stack that subscribes to `/camera/image_raw` from the Pi:

- `ros2 run aura_face_auth face_detector_node --ros-args -p det_thresh:=0.5 -p det_size:=640 -p process_every_n_frames:=2 -p execution_provider:='auto'`
- `ros2 run aura_face_auth recognizer_node --ros-args -p recognition_interval:=0.5 -p execution_provider:='auto' -p model_path:='~/.insightface/models/buffalo_s/w600k_mbf.onnx'`
- `ros2 run aura_face_auth liveness_node --ros-args -p liveness_threshold:=0.5 -p liveness_interval:=0.5 -p development_mode:=false -p dev_liveness_score:=1.0`
- `ros2 run aura_face_auth auth_node --ros-args -p similarity_threshold:=0.4 -p authentication_timeout:=60.0 -p reverify_interval:=10.0 -p allow_multiple_faces:=false -p min_quality:=0.3`
- `ros2 launch aura_behavior behavior.launch.py`
- `ros2 launch aura_follow human_follow.launch.py`
- `ros2 launch aura_voice voice.launch.py`
- `ros2 launch aura_alert alert.launch.py`

## Source verification

The checked code confirms:

- `camera_node` publishes `/camera/image_raw` in [src/aura_face_auth/aura_face_auth/camera_node.py](src/aura_face_auth/aura_face_auth/camera_node.py)
- `face_detector_node` subscribes to `/camera/image_raw` in [src/aura_face_auth/aura_face_auth/face_detector_node.py](src/aura_face_auth/aura_face_auth/face_detector_node.py)
- `behavior_node` subscribes to `/camera/image_raw` in [src/aura_behavior/aura_behavior/behavior_node.py](src/aura_behavior/aura_behavior/behavior_node.py)
- `human_follow_node` subscribes to `/camera/image_raw` and publishes `/cmd_vel` in [src/aura_follow/aura_follow/human_follow_node.py](src/aura_follow/aura_follow/human_follow_node.py)
- `aura_robot_hw` receives `/cmd_vel` via the ESP32 bridge path in [src/aura_robot_hw/aura_robot_hw/esp32_bridge.py](src/aura_robot_hw/aura_robot_hw/esp32_bridge.py)

## Startup scripts

```bash
cd ~/AURA_WS3
RPI_HOST=10.x.x.x ./scripts/start_aura_all.sh
```

Then:

```bash
tmux attach -t aura_rpi
tmux attach -t aura_laptop
```

## Stop

```bash
cd ~/AURA_WS3
RPI_HOST=10.x.x.x ./scripts/stop_aura_all.sh
```

## Notes

- No fake camera publisher is created.
- No laptop access to `/dev/video0` is attempted.
- The camera remains on the Pi and the laptop AI nodes consume the stream through ROS 2 DDS.
- All existing ROS topic names remain unchanged.
