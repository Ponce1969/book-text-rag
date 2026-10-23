"""Variantes editoriales de la comparación título↔encabezado (D-17 §2.2-§2.3).

Solo se admiten las marcas de parte declaradas —`Part <n>.` / `<ROMANO>.` al inicio y
`(Part <n>)` / `(<n>)` al final— y un guion de corte. La marca numérica debe coincidir cuando
ambos lados la declaran; el resto del título se sigue comparando por contención exacta o por sus
primeras cuatro palabras.
"""

from __future__ import annotations

import pytest

from book_text_rag.domain.anchor import core_title, covers


@pytest.mark.parametrize(
    ("title", "heading"),
    [
        (
            "I. Foundations of Graph-Based Agentic Systems",
            "Part I. Foundations of Graph- Based Agentic Systems",
        ),
        (
            "II. Setup: Building the Digital Twin of a Tech Stack",
            "Part II. Setup: Building the Digital Twin of a Tech Stack",
        ),
        (
            "Setup: Building the Digital Twin of a Tech Stack (Part II)",
            "Part II. Setup: Building the Digital Twin of a Tech Stack",
        ),
        ("1. Introduction", "Chapter 1. Introduction"),
        ("Beta (Part II)", "Part II. Beta"),
        ("Part I. Foundations of Graph-Based Systems", "Foundations of Graph-Based Systems"),
    ],
)
def test_variantes_editoriales_equivalentes(title: str, heading: str) -> None:
    """El título del outline y el encabezado impreso se reconocen como la misma unidad."""
    assert covers(heading, title)


@pytest.mark.parametrize(
    ("title", "heading"),
    [
        ("I. Foundations of Graph-Based Systems", "Part II. Foundations of Graph-Based Systems"),
        ("1. Alpha", "2. Alpha"),
        ("Setup (Part II)", "Setup (Part III)"),
        ("Part I.", "Part I."),
        ("Mix. A Cocktail", "A Cocktail"),
        ("MIX. A Cocktail", "A Cocktail"),
        ("The Part II of the Story", "The of the Story"),
        ("I. Foundations of Graph-Based Systems", "Part I. Foundations of Vector-Based Systems"),
    ],
)
def test_variantes_no_equivalentes_se_rechazan(title: str, heading: str) -> None:
    """Una marca de parte distinta, un resto vacío o un texto distinto no emparejan."""
    assert not covers(heading, title)


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("Chapter 1. Introduction to Building AI Applications", "Introduction to Building AI Applications"),
        ("1. Introduction to Building AI Applications", "Introduction to Building AI Applications"),
        ("I. Foundations of Graph-Based Systems", "I. Foundations of Graph-Based Systems"),
    ],
)
def test_core_title_conserva_su_contrato(title: str, expected: str) -> None:
    """`core_title` sigue quitando solo las formas ordinales que ya quitaba."""
    assert core_title(title) == expected
