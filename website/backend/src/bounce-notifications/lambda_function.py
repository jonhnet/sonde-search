import json
import boto3

SES_CLIENT = boto3.client('ses', region_name='us-west-2')
NOTIFY_EMAIL = 'jelson@gmail.com'
FROM_EMAIL = 'noreply@lectrobox.com'


def lambda_handler(event, context):
    for record in event['Records']:
        message = json.loads(record['Sns']['Message'])

        notification_type = message.get('notificationType', 'Unknown')

        if notification_type == 'Bounce':
            bounce = message['bounce']
            recipients = bounce.get('bouncedRecipients', [])
            bounce_type = bounce.get('bounceType', 'Unknown')
            bounce_subtype = bounce.get('bounceSubType', 'Unknown')
            timestamp = bounce.get('timestamp', 'Unknown')
            reporting_mta = bounce.get('reportingMTA', 'Unknown')

            recipient_lines = []
            for r in recipients:
                addr = r.get('emailAddress', 'Unknown')
                status = r.get('status', 'Unknown')
                diag = r.get('diagnosticCode', 'No diagnostic code provided')
                action = r.get('action', 'Unknown')
                recipient_lines.append(
                    f"  Address: {addr}\n"
                    f"  Status: {status}\n"
                    f"  Action: {action}\n"
                    f"  Diagnostic: {diag}"
                )

            mail = message.get('mail', {})
            original_from = mail.get('source', 'Unknown')
            original_subject = mail.get('commonHeaders', {}).get('subject', 'Unknown')
            message_id = mail.get('messageId', 'Unknown')

            body = (
                f"Bounce Type: {bounce_type} / {bounce_subtype}\n"
                f"Timestamp: {timestamp}\n"
                f"Reporting MTA: {reporting_mta}\n"
                f"Original From: {original_from}\n"
                f"Original Subject: {original_subject}\n"
                f"Message ID: {message_id}\n"
                f"\nRecipients:\n" +
                "\n\n".join(recipient_lines) +
                f"\n\n--- Raw JSON ---\n{json.dumps(message, indent=2)}"
            )

            subject = f"SES Bounce: {', '.join(r.get('emailAddress', '?') for r in recipients)} ({bounce_type})"

        elif notification_type == 'Complaint':
            complaint = message['complaint']
            recipients = complaint.get('complainedRecipients', [])
            feedback_type = complaint.get('complaintFeedbackType', 'Unknown')
            timestamp = complaint.get('timestamp', 'Unknown')

            body = (
                f"Complaint Type: {feedback_type}\n"
                f"Timestamp: {timestamp}\n"
                f"Recipients: {', '.join(r.get('emailAddress', '?') for r in recipients)}\n"
                f"\n--- Raw JSON ---\n{json.dumps(message, indent=2)}"
            )

            subject = f"SES Complaint: {', '.join(r.get('emailAddress', '?') for r in recipients)}"

        else:
            subject = f"SES Notification: {notification_type}"
            body = json.dumps(message, indent=2)

        SES_CLIENT.send_email(
            Source=FROM_EMAIL,
            Destination={'ToAddresses': [NOTIFY_EMAIL]},
            Message={
                'Subject': {'Data': subject},
                'Body': {'Text': {'Data': body}}
            }
        )

    return {'statusCode': 200}
