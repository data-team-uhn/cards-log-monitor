#!/usr/bin/env python
# -*- coding: utf-8 -*-

# Licensed to the Apache Software Foundation (ASF) under one
# or more contributor license agreements.  See the NOTICE file
# distributed with this work for additional information
# regarding copyright ownership.  The ASF licenses this file
# to you under the Apache License, Version 2.0 (the
# "License"); you may not use this file except in compliance
# with the License.  You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing,
# software distributed under the License is distributed on an
# "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
# KIND, either express or implied.  See the License for the
# specific language governing permissions and limitations
# under the License.

import os
import json
import time
import hashlib
import datetime
import requests

LOKI_HOST = "http://localhost:3100"
if 'LOKI_HOST' in os.environ:
  LOKI_HOST = os.environ['LOKI_HOST']

SLACK_WEBHOOK_URL = None
if 'SLACK_WEBHOOK_URL' in os.environ:
  SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

# --- Begin COUNTERS initialization
if not os.path.isdir("COUNTERS"):
  os.mkdir("COUNTERS")

if not os.path.isdir("COUNTERS/EXPORT"):
  os.mkdir("COUNTERS/EXPORT")

if not os.path.isdir("COUNTERS/EXPORT/Subjects"):
  os.mkdir("COUNTERS/EXPORT/Subjects")

if not os.path.isdir("COUNTERS/EXPORT/Forms"):
  os.mkdir("COUNTERS/EXPORT/Forms")

# --- End COUNTERS initialization

def getExports(container_name, export_line, since=None):
  query_url = LOKI_HOST + "/loki/api/v1/query_range?query={name=\"" + container_name + "\"} |= `" + export_line + "`"
  if since is not None:
    query_url += "&start={}".format(1000000000 * since)
  resp = requests.get(query_url)
  if len(resp.json()['data']['result']) < 1:
    return []
  exports = []
  for log_entry in resp.json()['data']['result'][0]['values']:
    exports.append({'timestamp': int(log_entry[0]), 'container_name': container_name, 'message': log_entry[1].rstrip()})
  return exports

def saveCount(metric, value, cleanup=False):
  timestamp = int(time.time())
  counter_block = {}
  counter_block['timestamp'] = timestamp
  counter_block['value'] = value
  h = hashlib.sha256()
  h.update(json.dumps(counter_block, sort_keys=True).encode())
  counter_block['sha256'] = h.hexdigest()
  initial_directory_contents = os.listdir("COUNTERS/EXPORT/{}".format(metric))
  with open("COUNTERS/EXPORT/{}/{}.json".format(metric, timestamp), 'w') as f_json:
    json.dump(counter_block, f_json)
  if cleanup:
    for oldfile in initial_directory_contents:
      os.unlink(os.path.join("COUNTERS/EXPORT/{}".format(metric), oldfile))

def getValidCounterBlock(path):
  try:
    with open(path, 'r') as f_json:
      counter_block = json.load(f_json)
      hash_input_block = {}
      hash_input_block['timestamp'] = counter_block['timestamp']
      hash_input_block['value'] = counter_block['value']
      h = hashlib.sha256()
      h.update(json.dumps(hash_input_block, sort_keys=True).encode())
      if (counter_block['sha256'] == h.hexdigest()):
        return counter_block
  except:
    pass
  return None

def getLastValidCounterBlock(metric_path):
  max_timestamp = 0
  last_valid_counter_block = None
  for filename in os.listdir(metric_path):
    filepath = os.path.join(metric_path, filename)
    counter_block = getValidCounterBlock(filepath)
    if counter_block is None:
      continue
    if counter_block['timestamp'] > max_timestamp:
      max_timestamp = counter_block['timestamp']
      last_valid_counter_block = counter_block
  return last_valid_counter_block

prev_subjects_timestamp = None
prev_forms_timestamp = None

prev_subjects_counter_block = getLastValidCounterBlock("COUNTERS/EXPORT/Subjects")
if prev_subjects_counter_block is not None:
  prev_subjects_timestamp = prev_subjects_counter_block['timestamp']
else:
  prev_subjects_timestamp = None

prev_forms_counter_block = getLastValidCounterBlock("COUNTERS/EXPORT/Forms")
if prev_forms_counter_block is not None:
  prev_forms_timestamp = prev_forms_counter_block['timestamp']
else:
  prev_forms_timestamp = None

incremental_subject_exports_count = len(getExports("CARDS - Cards4CaRe", "ca.sickkids.ccm.lfs.cardiacrehab.internal.export.ExportTask Exported /Subjects/", since=prev_subjects_timestamp))
incremental_form_exports_count = len(getExports("CARDS - Cards4CaRe", "ca.sickkids.ccm.lfs.cardiacrehab.internal.export.ExportTask Exported /Forms/", since=prev_forms_timestamp))

if prev_subjects_counter_block is not None:
  total_subject_exports_count = prev_subjects_counter_block['value'] + incremental_subject_exports_count
else:
  total_subject_exports_count = incremental_subject_exports_count

if prev_forms_counter_block is not None:
  total_form_exports_count = prev_forms_counter_block['value'] + incremental_form_exports_count
else:
  total_form_exports_count = incremental_form_exports_count

saveCount("Subjects", total_subject_exports_count, cleanup=True)
saveCount("Forms", total_form_exports_count, cleanup=True)

slack_message = "*Exported Subjects* -- _Today:_ {}, _Total:_ {}\n".format(incremental_subject_exports_count, total_subject_exports_count)
slack_message += "*Exported Forms* -- _Today:_ {}, _Total:_ {}".format(incremental_form_exports_count, total_form_exports_count)

print(slack_message)

if SLACK_WEBHOOK_URL is not None:
  requests.post(SLACK_WEBHOOK_URL, json={'text': slack_message})
