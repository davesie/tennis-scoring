"""Display scraped WTB data in table format."""
import json
import sys


def show_data(json_file: str, limit: int = 20):
    """Show scraped data in table format."""

    with open(json_file, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Get clubs with players
    clubs_with_players = [item for item in data if item['players']]

    print("=" * 140)
    print(f"WTB SCRAPED DATA - Showing first {limit} clubs with players")
    print("=" * 140)
    print(f"Total clubs: {len(data)}")
    print(f"Clubs with Herren players: {len(clubs_with_players)}")
    print(f"Total Herren players: {sum(len(item['players']) for item in data)}")
    print("=" * 140)
    print()

    # Show table header
    print(f"{'Club Name':<40} {'WTB ID':<10} {'Rang':<6} {'LK':<6} {'Player Name':<35} {'Year':<6} {'ID-Nummer':<12} {'Nation':<8}")
    print("-" * 140)

    # Show first N clubs with players
    for item in clubs_with_players[:limit]:
        club = item['club']
        players = item['players']

        # First row - show club name + first player
        if players:
            p = players[0]
            print(f"{club['name']:<40} {club['wtb_id']:<10} {p['rang']:<6} {p['lk']:<6} {p['name']:<35} {str(p['birth_year'] or ''):<6} {p['id_nummer']:<12} {p['nation']:<8}")

            # Additional rows - just show players
            for p in players[1:]:
                print(f"{'':>51} {p['rang']:<6} {p['lk']:<6} {p['name']:<35} {str(p['birth_year'] or ''):<6} {p['id_nummer']:<12} {p['nation']:<8}")

        print("-" * 140)

    if len(clubs_with_players) > limit:
        print(f"\n... and {len(clubs_with_players) - limit} more clubs with players")

    print()
    print("=" * 140)


if __name__ == "__main__":
    json_file = sys.argv[1] if len(sys.argv) > 1 else "wtb_data_20260216_174541.json"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20

    show_data(json_file, limit)
