from rich.tree import Tree

from chaosforge.interfaces.cli.interactive.ui.console import console


def show_tree(title, root_name, items):

    tree = Tree(f"[bold bright_cyan]{root_name}[/bold bright_cyan]")

    for item in items:
        tree.add(f"[white]{item}[/white]")

    console.print()

    console.print(f"[bold bright_white]{title}[/bold bright_white]")

    console.print(tree)

    console.print()


def show_grouped_tree(title, groups):

    root = Tree(f"[bold bright_cyan]{title}[/bold bright_cyan]")

    for group_name, items in groups.items():
        branch = root.add(f"[bold yellow]{group_name}[/bold yellow]")

        for item in items:
            branch.add(f"[white]{item}[/white]")

    console.print(root)
