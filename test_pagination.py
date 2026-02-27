"""Test WTB pagination to see what URLs work."""
import httpx
from bs4 import BeautifulSoup
import asyncio
import re


async def test_pagination():
    """Test different pagination patterns."""

    base_url = "https://www.wtb-tennis.de"

    # Test different URL patterns
    test_urls = [
        f"{base_url}/spielbetrieb/vereine/",  # Page 1
        f"{base_url}/spielbetrieb/vereine/?page=2",  # Page 2 attempt 1
        f"{base_url}/spielbetrieb/vereine/page/2/",  # Page 2 attempt 2
        f"{base_url}/spielbetrieb/vereine?page=2",  # Page 2 attempt 3 (no trailing slash)
    ]

    async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
        for url in test_urls:
            print(f"\nTesting: {url}")
            print("-" * 80)

            try:
                response = await client.get(url)
                print(f"Status: {response.status_code}")
                print(f"Final URL: {response.url}")

                soup = BeautifulSoup(response.text, 'html.parser')

                # Find club links
                links = soup.select('a[href*="/spielbetrieb/vereine/verein/v/"]')

                if links:
                    # Get first 3 club IDs
                    club_ids = []
                    for link in links[:3]:
                        href = link.get('href', '')
                        match = re.search(r'/v/(\d+)', href)
                        if match:
                            club_ids.append(match.group(1))

                    print(f"Found {len(links)} clubs")
                    print(f"First 3 IDs: {', '.join(club_ids)}")
                else:
                    print("No clubs found!")

                    # Try to find pagination links
                    pagination = soup.find_all('a', class_='page-link')
                    if pagination:
                        print("\nPagination links found:")
                        for p in pagination[:5]:
                            print(f"  - {p.get('href', 'N/A')} ({p.text.strip()})")

                await asyncio.sleep(0.5)

            except Exception as e:
                print(f"Error: {e}")


if __name__ == "__main__":
    asyncio.run(test_pagination())
