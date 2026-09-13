import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import sessionmaker

import routers.chat as chat_module
from database import engine
from models import ChatMessage, PrivateDialog, User


class ChatDeliveryPersistenceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._original_push_sender = chat_module._send_chat_push_to_users
        chat_module._send_chat_push_to_users = lambda *args, **kwargs: None

    @classmethod
    def tearDownClass(cls):
        chat_module._send_chat_push_to_users = cls._original_push_sender

    def setUp(self):
        self.connection = engine.connect()
        self.transaction = self.connection.begin()
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.connection)
        self.db = self.SessionLocal()
        self.current_user = None

        self.user1 = User(username="chat_test_u1", hashed_password="x", is_active=True)
        self.user2 = User(username="chat_test_u2", hashed_password="x", is_active=True)
        self.db.add_all([self.user1, self.user2])
        self.db.flush()

        self.dialog = PrivateDialog(user1_id=self.user1.id, user2_id=self.user2.id)
        self.db.add(self.dialog)
        self.db.commit()
        self.db.refresh(self.dialog)
        self.current_user = self.user1

        app = FastAPI()
        app.include_router(chat_module.router)

        def override_get_db():
            yield self.db

        def override_get_chat_user():
            return self.current_user

        app.dependency_overrides[chat_module.get_db] = override_get_db
        app.dependency_overrides[chat_module.get_chat_user] = override_get_chat_user
        self.client = TestClient(app)

    def tearDown(self):
        self.db.close()
        self.transaction.rollback()
        self.connection.close()

    def test_private_message_is_saved_and_visible_for_recipient(self):
        send_resp = self.client.post(
            f"/api/chat/private/dialogs/{self.dialog.id}/messages",
            data={"text": "Тестовая доставка"},
        )
        self.assertEqual(send_resp.status_code, 201, send_resp.text)
        body = send_resp.json()
        self.assertEqual(body["display_text"], "Тестовая доставка")

        db_message = (
            self.db.query(ChatMessage)
            .filter(ChatMessage.private_dialog_id == self.dialog.id, ChatMessage.text == "Тестовая доставка")
            .order_by(ChatMessage.id.desc())
            .first()
        )
        self.assertIsNotNone(db_message, "Сообщение не записалось в chat_messages")
        self.assertEqual(db_message.sender_user_id, self.user1.id)

        self.current_user = self.user2
        list_resp = self.client.get(f"/api/chat/private/dialogs/{self.dialog.id}/messages")
        self.assertEqual(list_resp.status_code, 200, list_resp.text)
        items = list_resp.json()
        self.assertTrue(any(x["id"] == db_message.id for x in items), "Получатель не видит отправленное сообщение")


if __name__ == "__main__":
    unittest.main()

