#!/bin/bash
SAMPLE_WAV="${1:-$(find record/audio lab/sample_audio -name '*.wav' 2>/dev/null | head -n 1)}"
if [ -z "$SAMPLE_WAV" ] || [ ! -f "$SAMPLE_WAV" ]; then
  echo "Error: No wav file found to test."
  exit 1
fi
echo "Uploading $SAMPLE_WAV..."
RESPONSE=$(curl -s -X POST -F "file=@$SAMPLE_WAV" http://localhost:8080/upload-audio)
echo $RESPONSE
TASK_ID=$(echo $RESPONSE | grep -o '"task_id":"[^"]*' | cut -d'"' -f4)
echo "Task ID: $TASK_ID"

for i in {1..10}; do
  echo "Checking status (Attempt $i)..."
  curl -s http://localhost:8080/task/$TASK_ID
  echo ""
  sleep 4
done
