import os
import jwt
import logging

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class JWTManager:
    def __init__(self):
        self.secret_key = os.getenv('JWT_KEY', 'default_secret')
        self.algorithm = 'HS256'

    def verify_token(self, token):
        decoded_token = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
        return decoded_token

    def get_token_from_metadata(self, context):
        metadata = dict(context.invocation_metadata())
        if 'authorization' in metadata:
            logging.debug(f"Authorization value: {metadata['authorization']}")
            return metadata['authorization'].split(' ')[1]
        raise Exception('Token not found')
