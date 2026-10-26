"""Wytwarza 50 fikcyjnych spraw, z których 4 celowo mają błędy."""
import csv
from pathlib import Path
from models.case_schema import PESEL_WEIGHTS, REQUIRED_COLUMNS


def synthetic_pesel(index: int) -> str:
    """Syntaktycznie poprawny numer testowy, niepowiązany z realną osobą."""
    first_ten = "900101" + f"{index:04d}"
    checksum = (10 - sum(int(n) * w for n, w in zip(first_ten, PESEL_WEIGHTS)) % 10) % 10
    return first_ten + str(checksum)


def build_demo_rows() -> list[dict[str, str]]:
    rows = []
    for i in range(1, 51):
        person = f"Osoba Testowa {i:03d}"
        rows.append({
            "Sygnatura": f"DEMO/{i:03d}/2024",
            "Imie_Nazwisko": person,
            "PESEL": synthetic_pesel(i),
            "Kwota_Roszczenia": f"{1000 + i * 17},50",
            "Data_Wymagalnosci": "2024-01-15",
            "Opis_Stanu_Faktycznego": (
                f"W fikcyjnej sprawie {person} nie uregulowała testowej faktury "
                f"FV/{i:03d}/2024 w wyznaczonym terminie."
            ),
        })
    original = rows[6]["PESEL"]
    rows[6]["PESEL"] = original[:-1] + str((int(original[-1]) + 1) % 10)
    rows[17]["Kwota_Roszczenia"] = ""
    rows[31]["Data_Wymagalnosci"] = "2099-01-01"
    rows[44]["Opis_Stanu_Faktycznego"] = ""
    return rows


def main() -> None:
    target = Path(__file__).resolve().parent.parent / "data" / "sprawy_demo_50.csv"
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        writer.writerows(build_demo_rows())
    print(f"Zapisano {target} (50 fikcyjnych rekordów, 4 celowo błędne)")


if __name__ == "__main__":
    main()
