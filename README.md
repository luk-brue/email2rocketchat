## Exchange Group Inbox to RocketChat Bridge

**Main goal**: Filter mail inbox for specific emails (a typo3 contact form) and automatically post these in a RocketChat channel. 

## Prerequisites

- The email adress of an exchange group inbox
- Credentials for a member of the exchange group inbox
- Credentials for a RocketChat account with API access
- The name of a RocketChat channel, in which the account has the necessary rights to post a message. 
- The rocket chat instance server address

All of this information must be stored in a file named `.env` in the same directory as the python script. The file looks like this:

```
EMAIL_ADDRESS = "...@...."  
EMAIL_PASSWORD = "xxxxxxxxxxxxxx"  # Uni-Account Password
UK_NUMMER = "uk123456"             # Uni-Account username
RC_USER = "......."
RC_PASS = "xxxxxxxxxxxx"
RC_SERVER = "https://rocketchat.uni-kassel.de"
RC_CHANNEL = "#yourchannel"
```
If you can, restrict access to this file to all users except the one which is running the script. There are more secure alternatives which can be implemented but I do not have the time or expertise for this. 

## Setup

1. Have Python installed on the machine
1. Clone this repo
1. Optional: Create a virtual environment with `venv` or `conda`. 
1. Install the necessary dependencies listed in `requirements.txt`
1. Create a file named `.env` which contains the necessary information (see Prerequisites)
1. Activate the virtual environment and run the python script to test functionality
1. Optionally, create a systemd which spawns the script at startup and makes sure it is running for as long as the system is powered up. 

## Details about email filtering and processing

- The script only checks for mails in the INBOX folder (Posteingang). 
- It does not discern between read and unread mails (it is a group folder, so another person could have read the mail already)
- Typo3 contact form emails are discerned from other mail traffic, using a few criteria such as
    - X-Mailer Header used by Typo3
    - All sorts of replies containing the orginal contact form are filtered out
    - the mail body is scanned and expected to contain a few field names from the contact form
    - The email message ID (unique across all emails) is used to recognize emails that have already been sent to RocketChat as messages. 
        - To achieve this, the file `processed_emails.csv` is read if it exists. Otherwise it will be created later by the script. 
- If an email is identified as Typo3 contact form, it is parsed. 
    - The mail contains a HTML Table of the filled out Typo3 contact form. 
    - This table is parsed into a python dict
    - Some additional details, such as email subject, sender and date are parsed from other sources
- A message is posted to the specified RocketChat channel, containing a few key fields from the dict. 
    - The message is formatted using markdown. 
- A second message with details is posted as a thread under the first message, in order to clean up the channel the remaining fields are posted as a thread message. 
    - To achieve this, the message ID of the first message is retained and given as an argument to the thread posting function.
- If posting was successful, a record of the processed email is created. The email is identified by its unique email message ID. This record is written to a `.csv` file named `processed_emails.csv`, which will be created in the same directory as the script. 

## Flow

1. Startup: Connect to Accounts
1. Read CSV file of processed emails and create one if it does not exist.
1. Fetch all emails from INBOX
1. Clean up the CSV file - remove email IDs that are no longer in INBOX.
1. Process all emails from INBOX, unless their ID is in the CSV file
1. Start a 'streaming subscription' to get notifications for new emails.
1. Listen and wait for notifications
1. In case an email arrives, process it and listen for more notifications.
1. Renew the subscription after 30 minutes (maximum allowed connection time by EWS). 

## Efficiency concerns

The script does try to minimize resource usage. For example, by using the notification system, only new emails are fetched. `exchangelib` offers `item_sync`, which does work fine but not for this use case, as we need the `headers` field to stay intact - and as it turns out, it is silently removed by the sync functionality. So this implementation relies on classic `fetch` instead of syncing, which was made efficient by:

- only fetching the new email
- only fetching select fields which are necessary, and not getting attachments for example. 

## Known Shortcomings

- Credentials are stored in clear text in a config file and as environment variables. Which is ok, but not totally secure. 
- If the contact form field names are updated, the script has to be updated as well. Otherwise it breaks and the contact form is not transported correctly. If you were eager, you could implement a fallback for this, which automatically posts the whole email to RocketChat and does not discern between field names. 




