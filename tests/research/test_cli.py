from research.workbench.__main__ import main


def test_web_server_keeps_credential_loading_in_shared_resolver(monkeypatch):
    options = []

    class App:
        def run(self, **kwargs):
            options.append(kwargs)

    monkeypatch.setattr(
        "research.workbench.web.create_app", lambda *args, **kwargs: App()
    )
    assert main(["serve"]) == 0
    assert options[0]["load_dotenv"] is False
