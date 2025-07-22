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
1. Optional: Create a virtual environment
1. Install the necessary dependencies listed in requirements.txt
1. Create a file named `.env` which contains the necessary information (see Prerequisites)
1. Activate the virtual environment and run the python script once to test functionality
1. Set up a cron job to run the script periodically. 

## Details about email filtering and processing

- The script only checks for mails in the INBOX folder (Posteingang). 
- It checks both read and unread mails (it is a group folder, so another person could have read the mail already)
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
- *Note:* Only required fields from the contact form are posted to RocketChat. Optional fields, such as `R Code` or `Datasets`, are ommitted for simplicity - but if you want, you can write a logic which checks for the presence of optional fields and posts them as well to the detail thread.
- If posting was successful, a record of the processed email is created. The email is identified by its unique email message ID. This record is written to a `.csv` file named `processed_emails.csv`, which will be created in the same directory as the script. 

## Known Shortcomings

- Only required fields of the contact form are posted to RocketChat
- the `.csv` file could grow large over the years if there is a lot of traffic and there should be a mechanism that reduces it to the emails which are currently residing in the INBOX folder. 
- Credentials are stored in clear text in a config file and as environment variables. Which is ok, but not totally secure. 
- If the contact form field names are updated, the script has to be updated as well. Otherwise it breaks and the contact form is not transported correctly. If you were eager, you could implement a fallback for this, which automatically posts the whole email to RocketChat and does not discern between field names. 
- Optimally, we would use the https://ecederstrand.github.io/exchangelib/#synchronization-subscriptions-and-notifications feature to receive notifications from Exchange Web Services and only run the script in case a new mail is in the INBOX




