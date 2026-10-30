from chaosforge.interfaces.cli.interactive.ui.console import console


def success(message):

    console.print(f"✔ {message}", style="success")


def error(message):

    console.print(f"✖ {message}", style="error")


def warning(message):

    console.print(f"⚠ {message}", style="warning")


def info(message):

    console.print(f"ℹ {message}", style="info")


def pending(message):

    console.print(f"◉ {message}", style="pending")


def running(message):

    console.print(f"⟳ {message}", style="running")


def completed(message):

    console.print(f"✔ {message}", style="completed")


def failed(message):

    console.print(f"✖ {message}", style="failed")
