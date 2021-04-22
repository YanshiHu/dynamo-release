from .scatters import scatters
from .scatters import docstrings

docstrings.delete_params("scatters.parameters", "adata", "basis")


@docstrings.with_indent(4)
def hdbscan(adata, basis="umap", color="hdbscan", *args, **kwargs):
    """\
    Scatter plot for hdbscan clustering in selected basis.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            an Annodata object.
        %(scatters.parameters.no_adata|basis)s

    Returns
    -------
        plots hdbscan clustering of the adata object.
    """

    return scatters(adata, basis=basis, color=color, *args, **kwargs)


@docstrings.with_indent(4)
def leiden(adata, basis="umap", color="leiden", *args, **kwargs):
    """\
   Scatter plot for leiden community detection in selected basis.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            an Annodata object.
        %(scatters.parameters.no_adata|basis)s

    Returns
    -------
        plots leiden clustering of the adata object.
    """

    return scatters(adata, basis=basis, color=color, *args, **kwargs)


@docstrings.with_indent(4)
def louvain(adata, basis="umap", color="louvain", *args, **kwargs):
    """\
    Scatter plot for louvain community detection in selected basis.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            an Annodata object.
        %(scatters.parameters.no_adata|basis)s

    Returns
    -------
        plots louvain clustering of the adata object.
    """

    return scatters(adata, basis=basis, color=color, *args, **kwargs)


@docstrings.with_indent(4)
def infomap(adata, basis="umap", color="infomap", *args, **kwargs):
    """\
    Scatter plot for infomap community detection in selected basis.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            an Annodata object.
        %(scatters.parameters.no_adata|basis)s

    Returns
    -------
        plots leiden clustering of the adata object.
    """

    return scatters(adata, basis=basis, color=color, *args, **kwargs)
