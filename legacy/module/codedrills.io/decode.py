#!/usr/bin/env python3


import base64
import json

import blackboxprotobuf
import fire


def main(input_file, output_file):
    with open(input_file, 'r') as fo:
        data = fo.read()

    data = base64.b64decode(data)
    size = int.from_bytes(data[:5], 'big')
    data = data[5:5 + size]

    message_type = {}
    for path in (
        ('1', '1', '3'),
        ('1', '1', '4'),
    ):
        d = message_type
        *path, key = path
        for k in path:
            d = d.setdefault(k, {'type': 'message', 'message_typedef': {}})
            d = d['message_typedef']
        d[key] = {'type': 'bytes'}

    message, types = blackboxprotobuf.decode_message(data, message_type)
    print(output_file)

    class ForceBytes2Str(json.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, bytes):
                return str(obj, encoding='utf-8')
            return json.JSONEncoder.default(self, obj)

    with open(output_file, 'w') as fo:
        json.dump(message, fo, cls=ForceBytes2Str, indent=2)


if __name__ == '__main__':
    fire.Fire(main)
