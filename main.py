from promptwriter.storage.app_files import ensure_app_files
from promptwriter.ui.app import PromptGeneratorApp


if __name__ == "__main__":
    ensure_app_files()
    app = PromptGeneratorApp()
    app.mainloop()
