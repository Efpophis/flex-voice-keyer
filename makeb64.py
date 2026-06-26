#!/usr/bin/env python3

import base64
import sys

file = sys.argv[1] 

with open(file, "rb") as img:
   b64b = base64.b64encode(img.read())

print(f"icon_b64 = {b64b}")

