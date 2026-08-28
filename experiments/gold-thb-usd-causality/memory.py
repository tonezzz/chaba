"""Rolling memory for the multi-head expert system.

Stores per-day context vectors and realized head returns. Fits a
NearestNeighbors index on demand and queries it for the k most similar
historical contexts.
"""
import numpy as np
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import StandardScaler


class Memory:
    """Causal memory: stores only past days; query must use data up to t-1."""

    def __init__(self, k: int = 50, metric: str = "euclidean"):
        self.k = k
        self.metric = metric
        self.contexts = []
        self.head_returns = []
        self.dates = []
        self._nn = None
        self._scaler = None
        self._fitted = False

    def append(self, context: np.ndarray, head_returns: np.ndarray, date):
        """Append a single historical record."""
        self.contexts.append(np.asarray(context, dtype=np.float64))
        self.head_returns.append(np.asarray(head_returns, dtype=np.float64))
        self.dates.append(date)
        self._fitted = False

    def fit(self):
        """Fit the k-NN index on all stored contexts."""
        n = len(self.contexts)
        if n < max(self.k, 2):
            self._fitted = False
            return
        X = np.array(self.contexts)
        self._scaler = StandardScaler().fit(X)
        Xs = self._scaler.transform(X)
        n_neighbors = min(self.k, n)
        self._nn = NearestNeighbors(n_neighbors=n_neighbors, metric=self.metric)
        self._nn.fit(Xs)
        self._fitted = True

    def query(self, context: np.ndarray):
        """Return the kxN head-return matrix for the k nearest stored contexts."""
        if not self._fitted or self._nn is None:
            return None
        q = np.asarray(context, dtype=np.float64).reshape(1, -1)
        q = self._scaler.transform(q)
        dists, idx = self._nn.kneighbors(q)
        return np.array([self.head_returns[i] for i in idx[0]])

    def __len__(self):
        return len(self.contexts)
