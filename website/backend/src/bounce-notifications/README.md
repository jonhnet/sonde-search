## SES Bounce/Complaint Notifications

The sonde notifier sends emails via AWS SES. This Lambda function
forwards bounce and complaint notifications to an admin email so we
can detect delivery problems.

### Architecture

SES → SNS topic → Lambda → admin email

- `lambda_function.py`: Parses SNS bounce/complaint events and sends
  a formatted summary email.
- `setup.sh`: Creates the IAM role, Lambda function, SNS subscription,
  and permissions. Idempotent — safe to re-run.

### Setup

```
./setup.sh
```

The script prints a test command at the end to verify the pipeline works.
