"""Test suite for Gamification and Trivia Engine."""
from __future__ import annotations

import json
import unittest

from app import create_app
from models import TriviaQuestion, User, VisitorBadge, VisitorTriviaLog, db


class GamificationTriviaTestCase(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.app.config["WTF_CSRF_ENABLED"] = False
        self.client = self.app.test_client()

        with self.app.app_context():
            # Test user
            self.user = User.query.filter_by(email="trivia_tester@example.com").first()
            if not self.user:
                self.user = User(
                    email="trivia_tester@example.com",
                    username="triviatester",
                    role="visitor",
                    full_name="Trivia Tester",
                    status="active",
                )
                self.user.set_password("Password123!")
                db.session.add(self.user)
                db.session.commit()
            self.user_id = self.user.id
            self.user_email = self.user.email

            # Test question
            self.question = TriviaQuestion.query.filter_by(question="How many vertebrae does a giraffe have?").first()
            if not self.question:
                self.question = TriviaQuestion(
                    category="Gentle Giants",
                    difficulty="easy",
                    question="How many vertebrae does a giraffe have?",
                    options=["7 vertebrae", "14 vertebrae", "21 vertebrae", "28 vertebrae"],
                    correct_option_index=0,
                    explanation="Giraffes have exactly 7 neck vertebrae, the same as humans!",
                    points_reward=20,
                    is_active=True,
                )
                db.session.add(self.question)
                db.session.commit()
            self.question_id = self.question.id

    def test_trivia_submission_correct_and_badge_unlock(self):
        with self.client.session_transaction() as sess:
            sess["user_id"] = self.user_id
            sess["role"] = "visitor"
            sess["auth_by_role"] = {"visitor": {"user_id": self.user_id, "email": self.user_email}}

        with self.app.app_context():
            # Clean up previous test logs for clean assertion
            VisitorTriviaLog.query.filter_by(user_id=self.user_id).delete()
            VisitorBadge.query.filter_by(user_id=self.user_id).delete()
            db.session.commit()

        # Submit correct answer (option index 0)
        res = self.client.post(
            "/visitor/api/trivia/submit",
            data=json.dumps({"question_id": self.question_id, "selected_option": 0}),
            content_type="application/json",
        )
        self.assertEqual(res.status_code, 200)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertTrue(data["is_correct"])
        self.assertEqual(data["correct_index"], 0)
        self.assertEqual(data["points_awarded"], 20)
        self.assertIn("junior_explorer", data["newly_unlocked_badges"])

        # Second attempt for same question should award 0 points (prevent farming)
        res2 = self.client.post(
            "/visitor/api/trivia/submit",
            data=json.dumps({"question_id": self.question_id, "selected_option": 0}),
            content_type="application/json",
        )
        self.assertEqual(res2.status_code, 200)
        data2 = res2.get_json()
        self.assertTrue(data2["is_correct"])
        self.assertEqual(data2["points_awarded"], 0)


if __name__ == "__main__":
    unittest.main()
