#!/usr/bin/env python3
"""Generate data/customers.csv: 1,240 made-up customers for the demo.

Every value is synthetic. Company names are built from word lists, phone
numbers use the 555-01xx range reserved for fiction, and e-mail addresses use
example.com, so nothing here can belong to a real business. The generator is
seeded, so every run writes the same file.
"""
import csv
import os
import random

ROWS = 1240
FIELDS = ["customer", "region", "city", "phone", "email", "plan", "annual_value_usd", "customer_since"]

FIRST = ["Acme", "Bright", "Copper", "Driftwood", "Evergreen", "Foxglove", "Granite", "Harbor",
         "Ironwood", "Juniper", "Kestrel", "Lantern", "Maple", "Northwind", "Oakline", "Pinecrest",
         "Quarry", "Redstone", "Silverleaf", "Tidewater", "Upland", "Valley", "Willow", "Yarrow"]
SECOND = ["Bakery", "Florist", "Hardware", "Dental", "Fitness", "Print Shop", "Coffee", "Garage",
          "Books", "Pet Supply", "Tailors", "Bicycles", "Pharmacy", "Optics", "Catering", "Studio"]
SUFFIX = ["Co.", "LLC", "Inc.", "& Sons", "Group", "Partners"]
REGIONS = {
    "North-East": ["Boston", "Hartford", "Providence", "Albany"],
    "South-East": ["Atlanta", "Charlotte", "Orlando", "Nashville"],
    "Midwest": ["Chicago", "Columbus", "Madison", "Omaha"],
    "South-West": ["Phoenix", "Austin", "Albuquerque", "Tucson"],
    "West": ["Denver", "Sacramento", "Salt Lake City", "Reno"],
    "North-West": ["Seattle", "Portland", "Boise", "Spokane"],
}
PLANS = ["Starter", "Growth", "Pro", "Enterprise"]


def build():
    rng = random.Random(20261103)
    seen, rows = set(), []
    # The demo's customer comes first so the video and the tests can name it.
    rows.append({"customer": "Acme Bakery Co.", "region": "North-East", "city": "Boston",
                 "phone": "+1-617-555-0142", "email": "orders@acme-bakery.example.com",
                 "plan": "Growth", "annual_value_usd": "48200", "customer_since": "2021-04-12"})
    seen.add("Acme Bakery Co.")
    while len(rows) < ROWS:
        name = "%s %s %s" % (rng.choice(FIRST), rng.choice(SECOND), rng.choice(SUFFIX))
        if name in seen:
            continue
        seen.add(name)
        region = rng.choice(sorted(REGIONS))
        slug = "".join(ch for ch in name.lower().replace("&", "and") if ch.isalnum() or ch == " ").replace(" ", "-")
        rows.append({
            "customer": name,
            "region": region,
            "city": rng.choice(REGIONS[region]),
            "phone": "+1-%03d-555-01%02d" % (rng.randint(201, 989), rng.randint(0, 99)),
            "email": "hello@%s.example.com" % slug,
            "plan": rng.choice(PLANS),
            "annual_value_usd": str(rng.randrange(3000, 250000, 100)),
            "customer_since": "%d-%02d-%02d" % (rng.randint(2014, 2026), rng.randint(1, 12), rng.randint(1, 28)),
        })
    return rows


def main():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "customers.csv")
    with open(path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(build())
    print("wrote %d customers to %s" % (ROWS, path))


if __name__ == "__main__":
    main()
