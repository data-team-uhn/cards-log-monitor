#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time

# Number of seconds before "now" that we can declare at said point that there
# have been no logged failures
LAST_CHECKPOINT_BUFFER_MARGIN_SECONDS = 1800

# Timestamp (in seconds) which this script has started at
START_TIME_SEC = time.time()

def setErrorFreeCheckpoint(timestamp_ns):
  with open("last_error_free_checkpoint.txt", 'w') as f:
    f.write(str(timestamp_ns))

setErrorFreeCheckpoint(int((START_TIME_SEC - LAST_CHECKPOINT_BUFFER_MARGIN_SECONDS) * 1000000000))
