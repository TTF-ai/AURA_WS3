import time
import unittest

from aura_face_auth.auth_node import AuthNode, AuthState


class AuthLockLogicTests(unittest.TestCase):
    def test_authenticated_user_remains_active_when_another_face_appears(self):
        node = AuthNode.__new__(AuthNode)

        node.state = AuthState.AUTHENTICATED
        node.authenticated_username = "alice"
        node.authenticated_user_id = 7
        node.authenticated_face_id = 2
        node.best_similarity = 0.92
        node.auth_time = time.time()
        node.last_reverify_time = time.time()
        node.lock_time = 0.0
        node.recovery_until = 0.0
        node.authentication_timeout = 60.0
        node.reverify_interval = 10.0
        node.lock_cooldown = 3.0
        node.recovery_timeout = 15.0
        node.allow_multiple_faces = False
        node.latest_num_faces = 2
        node.face_timeout = 5.0
        node.last_face_seen_time = time.time()
        node._is_authenticated_face_active = lambda now: True
        node._publish_status = lambda now: None

        node.evaluate_auth()

        self.assertEqual(node.state, AuthState.AUTHENTICATED)
        self.assertEqual(node.authenticated_face_id, 2)
        self.assertEqual(node.authenticated_username, "alice")


if __name__ == "__main__":
    unittest.main()
