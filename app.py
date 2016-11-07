from flask import Flask, request
from flask_restful import abort, reqparse, Resource, Api
from messengerbot import MessengerClient, messages

from history import API as History_API
from ai import BotAI

import logging
import os


app = Flask(__name__)
# Configure app.
_access_token = os.environ.get('CHRONOLOGIST_ACCESS_TOKEN')
_verify_token = os.environ.get('CHRONOLOGIST_VERIFY_TOKEN')
_api_ai_token = os.environ.get('CHRONOLOGIST_API_AI_TOKEN')

if _access_token is None:
    raise RecursionError('`CHRONOLOGIST_ACCESS_TOKEN` env var is not set')
app.config.update(
    DEBUG=eval(os.environ.get('CHRONOLOGIST_DEBUG', 'False')),
    VERIFY_TOKEN=_verify_token,
    ACCESS_TOKEN=_access_token
)
api = Api(app)
history_api = History_API()
messenger = MessengerClient(access_token=app.config['ACCESS_TOKEN'])
# Logging.
gunicorn_error_logger = logging.getLogger('gunicorn.error')
app.logger.handlers.extend(gunicorn_error_logger.handlers)
app.logger.setLevel(logging.DEBUG if app.config['DEBUG'] else logging.INFO)


class Bot(Resource):
    def __init__(self):
        self.bot_ai = BotAI(_api_ai_token)

    def get(self):
        parser = reqparse.RequestParser()
        parser.add_argument('hub.challenge', type=int)
        parser.add_argument('hub.mode')
        parser.add_argument('hub.verify_token')
        args = parser.parse_args()
        if args['hub.verify_token'] == app.config['VERIFY_TOKEN']:
            return args['hub.challenge'], 202
        abort(401, message='Invalid verify token')

    def post(self):
        events = request.json['entry'][0]['messaging']
        for event in events:
            if (event.get('message') and event['message'].get('text')):
                rqsts = self._build_messages(event['sender']['id'], event['message']['text'])
                for rqst in rqsts:
                    messenger.send(rqst)
        return 200

    def _fetch_history(self, date, year=None):
        '''Fetches the history and prepares the response.'''
        items = []
        for item in history_api.date(date.month, date.day, year):
            items.append(messages.Message(text=str(item)))
        if not items:
            items.append(messages.Message(text='Nothing special found for this date in history'))
        return items

    def _build_messages(self, recipient_id, incoming):
        '''Constructs the response message according to the incoming message. Returns the messenger request.'''
        recipient = messages.Recipient(recipient_id=recipient_id)
        action = self.bot_ai.extract_action(incoming)

        if action.fulfillment:
            app.logger.info('Parsed action: fulfillment')
            items = [messages.Message(text=action.fulfillment)]
        elif action.name == 'history':
            app.logger.info('Parsed action: history, date: %s, year: %s', action.date.strftime('%-d %B %Y'),
                            action.year)
            items = self._fetch_history(action.date, action.year)
            if not action.year:
                items = items[:3]
        else:
            app.logger.warning('Could not parse the action')
            items = []

        return [messages.MessageRequest(recipient, item) for item in items]


api.add_resource(Bot, '/')


if __name__ == '__main__':
    app.run()
