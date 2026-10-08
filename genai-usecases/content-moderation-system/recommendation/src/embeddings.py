"""
Stage 2: text embeddings for relevance and precedent retrieval, behind a small interface.

The default implementation is TF-IDF with cosine similarity, written with numpy only.
It was chosen over a sentence-embedding model because it needs no model download, runs
without a network, is fully deterministic and adds no dependency beyond numpy, which the
project already installs. Item metadata here is short category and topic labels, where
lexical overlap is most of the signal. Anything that implements ``EmbeddingProvider``
(for example a sentence-transformers wrapper) can be passed in its place.
"""

import math
import re
from collections import Counter
from typing import Dict, List, Protocol, Sequence

import numpy as np

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    """Lower-case alphanumeric tokens; underscores and punctuation separate words."""
    return _TOKEN.findall(str(text).lower())


class EmbeddingProvider(Protocol):
    """Turns texts into L2-normalised row vectors, so a dot product is cosine similarity."""

    def fit(self, texts: Sequence[str]) -> None: ...

    def embed(self, texts: Sequence[str]) -> np.ndarray: ...


class TfidfEmbeddingProvider:
    """TF-IDF vectors with smoothed inverse document frequency."""

    def __init__(self) -> None:
        self.vocabulary: Dict[str, int] = {}
        self.idf: np.ndarray = np.zeros(0)

    def fit(self, texts: Sequence[str]) -> None:
        document_frequency: Counter = Counter()
        for text in texts:
            document_frequency.update(set(tokenize(text)))
        terms = sorted(document_frequency)
        self.vocabulary = {term: index for index, term in enumerate(terms)}
        count = len(texts)
        self.idf = np.array(
            [math.log((1 + count) / (1 + document_frequency[term])) + 1.0 for term in terms]
        )

    def embed(self, texts: Sequence[str]) -> np.ndarray:
        matrix = np.zeros((len(texts), len(self.vocabulary)))
        for row, text in enumerate(texts):
            for term, frequency in Counter(tokenize(text)).items():
                column = self.vocabulary.get(term)
                if column is not None:
                    matrix[row, column] = frequency * self.idf[column]
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0.0] = 1.0
        return matrix / norms


def cosine_scores(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one query vector against each row of a normalised matrix."""
    norm = float(np.linalg.norm(query))
    if norm == 0.0 or matrix.size == 0:
        return np.zeros(matrix.shape[0])
    return matrix @ (query / norm)
