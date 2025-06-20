# BTC Hunter

Simple tool to check lists of BIP39 mnemonics and brainwallet passwords.

## Requirements

Install dependencies listed in `requirements.txt` using pip. A helper script
`run.sh` is provided.

## Usage

1. Export Telegram credentials:

```bash
export TELEGRAM_TOKEN="<your token>"
export TELEGRAM_CHAT_ID="<your chat id>"
```

2. Run the script:

```bash
./run.sh
```

Word lists must be located in the same directory as the script. If
`broken_seeds.txt` is missing it will be ignored.
