# login_data_pb2.py
# Minimal generic decoder for GetLoginData response.
# The real response is a nested protobuf; we capture the raw bytes of
# field 8 (the outer wrapper) and expose any embedded JWT string.

from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

_FILE = descriptor_pb2.FileDescriptorProto()
_FILE.name = "login_data.proto"
_FILE.package = "login_data"
_FILE.syntax = "proto3"

msg = _FILE.message_type.add()
msg.name = "LoginData"

# field 1: raw wrapper bytes (the whole outer field-8 payload)
f1 = msg.field.add()
f1.name = "raw_payload"
f1.number = 1
f1.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
f1.type = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES

# field 2: extracted JWT (if present)
f2 = msg.field.add()
f2.name = "jwt"
f2.number = 2
f2.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
f2.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

_pool = descriptor_pool.DescriptorPool()
_pool.Add(_FILE)
LoginData = message_factory.GetMessageClass(_pool.FindMessageTypeByName("login_data.LoginData"))