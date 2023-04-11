#!/usr/bin/env python
# -*- coding: utf-8 -*-

import re
import os
import sys
import time
import datetime
import requests

ERROR_LOG_TEXT = os.environ['ERROR_LOG_TEXT']
MONITORED_CONTAINER_PRETTY_NAME = os.environ['MONITORED_CONTAINER_PRETTY_NAME']

LOKI_HOST = "http://localhost:3100"
if 'LOKI_HOST' in os.environ:
  LOKI_HOST = os.environ['LOKI_HOST']

SLACK_WEBHOOK_URL = None
if 'SLACK_WEBHOOK_URL' in os.environ:
  SLACK_WEBHOOK_URL = os.environ['SLACK_WEBHOOK_URL']

# Look backwards through the logs by these many minutes when querying with LogQL
LOGS_LOOK_BACK_TIME = 7 * 24 * 60

# Number of seconds before "now" that we can declare at said point that there
# have been no logged failures
LAST_CHECKPOINT_BUFFER_MARGIN_SECONDS = 1800

# Timestamp (in seconds) which this script has started at
START_TIME_SEC = time.time()

MESSAGE_BRACKETS_OPEN = "({[<"
MESSAGE_BRACKETS_CLOSE = ")}]>"

def getISOStringTimestamp(loki_timestamp):
  return datetime.datetime.fromtimestamp(int(loki_timestamp) / 1000000000).isoformat()

def getPrettyStringTimestamp(loki_timestamp):
  return datetime.datetime.fromtimestamp(int(loki_timestamp) / 1000000000).strftime("%Y-%m-%d %H:%M:%S")

def removeBracketedText(message):
  filtered_string = ""
  opening_bracket = None
  expected_closing_bracket = None
  depth = 0
  for c in message:
    if (opening_bracket == None) and (c in MESSAGE_BRACKETS_OPEN):
      opening_bracket = c
      depth += 1
      expected_closing_bracket = MESSAGE_BRACKETS_CLOSE[MESSAGE_BRACKETS_OPEN.index(c)]
      continue

    if c == opening_bracket:
      depth += 1
      continue

    if c == expected_closing_bracket:
      depth -= 1
      if depth == 0:
        opening_bracket = None
        expected_closing_bracket = None
      continue

    if depth == 0:
      filtered_string += c

  return filtered_string

def removeLeadingDate(message):
  return re.sub('^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}:\d{2}\.\d{3} ', '', message)

def getLastFixTime(fix_type):
  resp = requests.get(LOKI_HOST + "/loki/api/v1/query_range?query={filename=\"/manual_fixes.log\", fixes=\"" + fix_type + "\"}&start=" + str(int(1000000000 * (time.time() - 60*LOGS_LOOK_BACK_TIME))))
  try:
    return int(resp.json()['data']['result'][0]['values'][0][0])
  except (KeyError, IndexError) as e:
    return 0

def getErrorsSince(container_name, error_line, start_time):
  resp = requests.get(LOKI_HOST + "/loki/api/v1/query_range?query={name=\"" + container_name + "\"} |= `" + error_line + "`&start=" + str(start_time))
  if len(resp.json()['data']['result']) < 1:
    return []
  errors = []
  for log_entry in resp.json()['data']['result'][0]['values']:
    errors.append({'timestamp': int(log_entry[0]), 'container_name': container_name, 'message': log_entry[1].rstrip()})
  return errors

# By default, get the following 250000000 nanoseconds = 0.25 seconds of context after the error
def getContext(container_name, loki_timestamp, context_length=250000000, require_tab_start=True):
  resp = requests.get(LOKI_HOST + "/loki/api/v1/query_range?query={name=\"" + container_name + "\"}&start=" + str(loki_timestamp) + "&end=" + str(loki_timestamp + context_length) + "&direction=forward")
  context = ""
  tab_started = False
  for context_piece in resp.json()['data']['result'][0]['values']:
    if not tab_started:
      tab_started = context_piece[1].startswith('\t')
    if require_tab_start and tab_started and (not context_piece[1].startswith('\t')):
      return context
    context += context_piece[1]
  return context

def addContextToErrors(errors):
  errors_with_context = []
  for error in errors:
    container_name = error['container_name']
    timestamp = error['timestamp']
    context_lines = getContext(container_name, timestamp)
    this_error = {}
    for error_field in error:
      if error_field == 'message':
        if len(context_lines) > 0:
          this_error[error_field] = context_lines
        else:
          this_error[error_field] = error[error_field]
      else:
        this_error[error_field] = error[error_field]
    this_error['stack_trace'] = []
    this_error['summary'] = []
    this_error['summary_searchable'] = []
    for context_line in context_lines.split('\n'):
      if context_line.lstrip().rstrip() == "":
        continue
      if context_line.startswith('\t'):
        this_error['stack_trace'].append(context_line.rstrip())
      else:
        this_error['summary'].append(context_line.lstrip().rstrip())
        this_error['summary_searchable'].append(removeBracketedText(removeLeadingDate(context_line.lstrip().rstrip())))
    errors_with_context.append(this_error)
  return errors_with_context

def getErrorFreeCheckpoint():
  with open("last_error_free_checkpoint.txt", 'r') as f:
    return int(f.read())

def setErrorFreeCheckpoint(timestamp_ns):
  with open("last_error_free_checkpoint.txt", 'w') as f:
    f.write(str(timestamp_ns))

try:
  # Get the timestamp of the last time that the error was manually resolved
  last_fix_time = getLastFixTime(ERROR_LOG_TEXT)

  # Get the timestamp that this was last known to work
  last_working_timestamp = getErrorFreeCheckpoint()

  # Select the more recent known-to-work timestamp
  last_working_timestamp = max(last_working_timestamp, last_fix_time)

  # If last_working_timestamp is from more than LOGS_LOOK_BACK_TIME minutes ago, something is not working correctly
  if ((START_TIME_SEC * 1000000000) - last_working_timestamp) > (LOGS_LOOK_BACK_TIME * 60 * 1000000000):
    raise Exception("Last working timestamp is too far in the past")

  # Get the errors that have been thrown since the last timestamp known to work
  errors = getErrorsSince(MONITORED_CONTAINER_PRETTY_NAME, ERROR_LOG_TEXT, last_working_timestamp)

  # Basic summary of S3 export activity
  error_summary_message = "As of _{}_, there have been *{}* failed S3 data exports ".format(getPrettyStringTimestamp(last_working_timestamp), len(errors))
  print(error_summary_message.rstrip())
  if len(errors) > 0:
    error_summary_message += ":boom:"
  else:
    error_summary_message += ":white_check_mark:"
    setErrorFreeCheckpoint(int((START_TIME_SEC - LAST_CHECKPOINT_BUFFER_MARGIN_SECONDS) * 1000000000))

  # Add context to the error lines to make them more meaningful
  augmented_errors = addContextToErrors(errors)

  # Aggregate the data
  aggregated_failures = {}
  for augmented_error in augmented_errors:
    failure_summary_key = '\n'.join(augmented_error['summary_searchable'])
    failure_stack_trace_key = '\n'.join(augmented_error['stack_trace'])
    failure_key = failure_summary_key + "\n" + failure_stack_trace_key
    if failure_key not in aggregated_failures:
      aggregated_failures[failure_key] = 0
    aggregated_failures[failure_key] += 1
except:
  error_summary_message = "Log monitoring script did not run properly. There may be failed S3 exports"
  print(error_summary_message)
  if SLACK_WEBHOOK_URL is not None:
    slack_attachments = []
    slack_attachment = {}
    slack_attachment['text'] = error_summary_message + " :warning:"
    slack_attachment['fallback'] = "Failed to generate a report :("
    slack_attachment['color'] = "#f3db0e"
    slack_attachments.append(slack_attachment)
    requests.post(SLACK_WEBHOOK_URL, json={'attachments': slack_attachments})
  sys.exit(1)

# POST a summary of the alerts to a Slack webhook
if SLACK_WEBHOOK_URL is not None:
  slack_text = error_summary_message
  for failure in aggregated_failures:
    slack_text += "\n"
    slack_text += ":arrow_right: *{}* of:".format(aggregated_failures[failure])
    slack_text += "\n"
    slack_text += "```"
    slack_text += "\n"
    slack_text += failure
    slack_text += "\n"
    slack_text += "```"

  slack_attachments = []
  slack_attachment = {}
  slack_attachment['text'] = slack_text
  slack_attachment['fallback'] = "Failed to generate a report :("
  if len(errors) == 0:
    slack_attachment['color'] = "#2eb886"
  else:
    slack_attachment['color'] = "#d70000"
  slack_attachments.append(slack_attachment)
  requests.post(SLACK_WEBHOOK_URL, json={'attachments': slack_attachments})
