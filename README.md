# GhostAI

**A lightweight, cross-platform AI assistant built with Python.**

GhostAI is a command-line AI assistant focused on simplicity, flexibility and performance. Built using Python's standard library, it aims to provide an accessible way to interact with AI models without unnecessary dependencies.

<p align="center">
  <img src="https://img.shields.io/badge/version-0.1.0-8A63D2?style=for-the-badge" alt="Version">
  <img src="https://img.shields.io/badge/Python-3.8%2B-3776AB?style=for-the-badge&logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Tests-*SOON-006400?style=for-the-badge" alt="Dependencies">
</p>

---

## Features

- **Lightweight:** Uses Python's built-in standard library.
- **Cross-platform:** Designed for Linux and Windows.
- **Model selection:** Choose between available AI models.
- **Conversation history:** Maintain context throughout a session.
- **Custom system prompts:** Configure the assistant's behaviour.
- **Simple interface:** Easy-to-use command-line experience.

## Requirements

- Python 3.8 or newer
- An internet connection
- Access to a supported AI provider

## Installation

Clone the repository:

```bash
git clone https://github.com/enesx32/ghost-agent.git
cd ghost-agent
```

Run GhostAI:

```bash
python main.py
```

On Linux, you may need:

```bash
python3 main.py
```

## Commands

| Command | Description |
|---|---|
| `/help` | Display available commands |
| `/model` | View and select models |
| `/reset` | Clear conversation history |
| `/clear` | Clear the terminal |
| `/exit` | Exit GhostAI |

## Project Structure

```
ghost-agent/
├── main.py
├── config.json
├── models.json
├── README.md
├── CONTRIBUTING.md
└── .gitignore
```

*The project structure may change as development continues.*

## Testing

GhostAI is still under development.

Automated tests are being planned. See the [Contributing Guidelines](CONTRIBUTING.md) for testing requirements.

## Roadmap

- [x] Initial command-line interface
- [x] Configuration support
- [x] Model selection
- [ ] Automated test suite
- [ ] Improved error handling
- [ ] Conversation export
- [ ] Configuration improvements

## Contributing

Contributions are welcome!

Whether it's a bug fix, improvement or new feature, feel free to get involved.

Please read [CONTRIBUTING.md](CONTRIBUTING.md) before submitting changes.

## License

License information will be added in a future release.
