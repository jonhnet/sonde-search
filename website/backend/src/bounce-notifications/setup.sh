#!/bin/bash
set -euo pipefail

REGION="us-west-2"
ACCOUNT_ID="234637635016"
FUNCTION_NAME="ses-bounce-notifier"
ROLE_NAME="ses-bounce-notifier-role"
SNS_TOPIC_ARN="arn:aws:sns:${REGION}:${ACCOUNT_ID}:ses-bounce-notifications"
LAMBDA_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== Step 1: Create IAM role ==="
ASSUME_ROLE_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Principal": {"Service": "lambda.amazonaws.com"},
    "Action": "sts:AssumeRole"
  }]
}'

ROLE_ARN=$(aws iam create-role \
  --role-name "$ROLE_NAME" \
  --assume-role-policy-document "$ASSUME_ROLE_POLICY" \
  --query 'Role.Arn' --output text 2>/dev/null) || {
    echo "Role may already exist, fetching ARN..."
    ROLE_ARN=$(aws iam get-role --role-name "$ROLE_NAME" --query 'Role.Arn' --output text)
}
echo "Role ARN: $ROLE_ARN"

echo "=== Step 2: Attach policies ==="
# CloudWatch Logs for debugging
aws iam attach-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-arn arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole

# SES send permission
INLINE_POLICY='{
  "Version": "2012-10-17",
  "Statement": [{
    "Effect": "Allow",
    "Action": "ses:SendEmail",
    "Resource": "*"
  }]
}'
aws iam put-role-policy \
  --role-name "$ROLE_NAME" \
  --policy-name ses-send-email \
  --policy-document "$INLINE_POLICY"

echo "Waiting 10s for IAM propagation..."
sleep 10

echo "=== Step 3: Package and create Lambda ==="
cd "$LAMBDA_DIR"
zip -j /tmp/ses-bounce-lambda.zip lambda_function.py

aws lambda create-function \
  --function-name "$FUNCTION_NAME" \
  --runtime python3.12 \
  --role "$ROLE_ARN" \
  --handler lambda_function.lambda_handler \
  --zip-file fileb:///tmp/ses-bounce-lambda.zip \
  --timeout 30 \
  --region "$REGION" 2>/dev/null || {
    echo "Function may already exist, updating code..."
    aws lambda update-function-code \
      --function-name "$FUNCTION_NAME" \
      --zip-file fileb:///tmp/ses-bounce-lambda.zip \
      --region "$REGION"
}

echo "=== Step 4: Allow SNS to invoke the Lambda ==="
aws lambda add-permission \
  --function-name "$FUNCTION_NAME" \
  --statement-id sns-bounce-invoke \
  --action lambda:InvokeFunction \
  --principal sns.amazonaws.com \
  --source-arn "$SNS_TOPIC_ARN" \
  --region "$REGION" 2>/dev/null || echo "Permission may already exist, continuing..."

echo "=== Step 5: Subscribe Lambda to SNS topic ==="
LAMBDA_ARN="arn:aws:lambda:${REGION}:${ACCOUNT_ID}:function:${FUNCTION_NAME}"

aws sns subscribe \
  --topic-arn "$SNS_TOPIC_ARN" \
  --protocol lambda \
  --notification-endpoint "$LAMBDA_ARN" \
  --region "$REGION"

echo "=== Step 6: Remove the Gmail email subscription ==="
echo "Listing current subscriptions..."
aws sns list-subscriptions-by-topic \
  --topic-arn "$SNS_TOPIC_ARN" \
  --region "$REGION"

echo ""
echo "=== Done! ==="
echo ""
echo "To test, run:"
echo "  aws ses send-email \\"
echo "    --from 'noreply@lectrobox.com' \\"
echo "    --destination 'ToAddresses=bounce@simulator.amazonses.com' \\"
echo "    --message 'Subject={Data=Bounce Test},Body={Text={Data=Testing bounce notification}}' \\"
echo "    --region $REGION"
echo ""
echo "If there are old email subscriptions listed above, you can remove them with:"
echo "  aws sns unsubscribe --subscription-arn <ARN> --region $REGION"
