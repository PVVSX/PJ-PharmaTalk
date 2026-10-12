#!/bin/bash
echo "Uploading..."
RESPONSE=$(curl -s -X POST -F "file=@/Users/pvvsx/Desktop/PJ/Pharmatalk_project/record/audio/12-09-26_13-58_000.wav" http://localhost:8080/upload-audio)
echo $RESPONSE
TASK_ID=$(echo $RESPONSE | grep -o '"task_id":"[^"]*' | cut -d'"' -f4)
echo "Task ID: $TASK_ID"

for i in {1..10}; do
  echo "Checking status (Attempt $i)..."
  curl -s http://localhost:8080/task/$TASK_ID
  echo ""
  sleep 4
done
