from ..tools.utils import update_dict
from .utils import save_fig


def cell_cycle(adata, cells=None,
                                save_show_or_return='show',
                                save_kwargs={},):
    """Plot a heatmap of cells ordered by cell cycle position

    Args:
        pop: CellPopulation instance
        cells: query string for cell properties (i.e. executes pop.cells.query(cells=cells))
        **kwargs: all other keyword arguments are passed to pop.where
    """
    import seaborn as sns
    import matplotlib.pyplot as plt

    if cells is None:
        cell_cycle_scores = adata.obsm['cell_cycle_phase'].dropna()
    else:
        cell_cycle_scores = adata[cells, :].obsm['cell_cycle_phase'].dropna().dropna()

    cell_cycle_scores.sort_values(['cell_cycle_phase', 'cell_cycle_progress'],
                                  ascending=[True, False],
                                  inplace=True)
    sns.heatmap(cell_cycle_scores[cell_cycle_scores.columns[:-2]].transpose(), annot=False, xticklabels=False,
                     linewidths=0)

    if save_show_or_return == "save":
        s_kwargs = {"path": None, "prefix": 'plot_direct_graph', "dpi": None,
                    "ext": 'pdf', "transparent": True, "close": True, "verbose": True}
        s_kwargs = update_dict(s_kwargs, save_kwargs)

        save_fig(**s_kwargs)
    elif save_show_or_return == "show":
        plt.tight_layout()
        plt.show()
    elif save_show_or_return == "return":
        return g
