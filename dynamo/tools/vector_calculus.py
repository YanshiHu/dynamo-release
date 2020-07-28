from tqdm import tqdm
import multiprocessing as mp
import itertools, functools
import numpy as np
from .utils import timeit, get_pd_row_column_idx
from .utils_vecCalc import vector_field_function, vecfld_from_adata, curl2d
from .scVectorField import vectorfield
from .sampling import sample_by_velocity, trn


@timeit
def elementwise_jacobian_transformation(fjac, X, qi, qj, return_J=False):
    """Inverse transform low dimension Jacobian matrix (:math:`\partial F_i / \partial x_j`) back to original space.
    The formula used to inverse transform Jacobian matrix calculated from low dimension (PCs) is:
                                            :math:`Jac = Q J Q^T`,
    where `Q, J, Jac` are the PCA loading matrix, low dimensional Jacobian matrix and the inverse transformed high
    dimensional Jacobian matrix. This function takes only one row from Q to form qi or qj.

    Parameters
    ----------
        fjac: `function`:
            The function for calculating numerical Jacobian matrix.
        X: `np.ndarray`:
            The samples coordinates with dimension n_obs x n_PCs, from which Jacobian will be calculated.
        Qi: `np.ndarray`:
            One sampled gene's PCs loading matrix with dimension n' x n_PCs, from which local dimension Jacobian matrix
            (k x k) will be inverse transformed back to high dimension.
        Qj: `np.ndarray`
            Another gene's (can be the same as those in Qi or different) PCs loading matrix with dimension  n' x n_PCs,
            from which local dimension Jacobian matrix (k x k) will be inverse transformed back to high dimension.
        return_J: `bool` (default: `False`)
            Whether to return the raw tensor of Jacobian matrix of each cell before transformation.

    Returns
    -------
        ret `np.ndarray`
            The calculated vector of Jacobian matrix (:math:`\partial F_i / \partial x_j`) for each cell.
    """

    Js = fjac(X)
    ret = np.zeros(len(X))
    for i in tqdm(range(len(X)), "calculating Jacobian for each cell"):
        J = Js[:, :, i]
        ret[i] = qi @ J @ qj

    if return_J:
        return ret, Js
    else:
        return ret

@timeit
def subset_jacobian_transformation(fjac, X, Qi, Qj, cores=1, return_J=False):
    """Transform Jacobian matrix (:math:`\partial F_i / \partial x_j`) from PCA space to the original space.
    The formula used for transformation:
                                            :math:`\hat{J} = Q J Q^T`,
    where `Q, J, \hat{J}` are the PCA loading matrix, low dimensional Jacobian matrix and the inverse transformed high
    dimensional Jacobian matrix. This function takes multiple rows from Q to form Qi or Qj.

    Parameters
    ----------
        fjac: `function`:
            The function for calculating numerical Jacobian matrix.
        X: `np.ndarray`:
            The samples coordinates with dimension n_obs x n_PCs, from which Jacobian will be calculated.
        Qi: `np.ndarray`:
            Sampled genes' PCA loading matrix with dimension n' x n_PCs, from which local dimension Jacobian matrix (k x k)
            will be inverse transformed back to high dimension.
        Qj: `np.ndarray`
            Sampled genes' (sample genes can be the same as those in Qi or different) PCs loading matrix with dimension
            n' x n_PCs, from which local dimension Jacobian matrix (k x k) will be inverse transformed back to high dimension.
        cores: `int` (default: 1):
            Number of cores to calculate Jacobian. If cores is set to be > 1, multiprocessing will be used to
            parallel the Jacobian calculation.
        return_J: `bool` (default: `False`)
            Whether to return the raw tensor of Jacobian matrix of each cell before transformation.

    Returns
    -------
        ret `np.ndarray`
            The calculated Jacobian matrix (n_gene x n_gene x n_obs) for each cell.
    """

    X = np.atleast_2d(X)
    Qi = np.atleast_2d(Qi)
    Qj = np.atleast_2d(Qj)
    d1, d2, n = Qi.shape[0], Qj.shape[0], X.shape[0]

    Js = fjac(X)
    ret = np.zeros((d1, d2, n))

    if cores == 1:
        #for i in tqdm(range(n), desc='Transforming subset Jacobian'):
        #    J = Js[:, :, i]
        #    ret[:, :, i] = Qi @ J @ Qj.T
        ret = transform_jacobian(Js, Qi, Qj, pbar=True)
    else:
        #pool = ThreadPool(cores)
        #res = pool.starmap(pool_cal_J, zip(np.arange(n), itertools.repeat(Js), itertools.repeat(Qi),
        #                              itertools.repeat(Qj), itertools.repeat(ret)))
        #pool.close()
        #pool.join()
        #ret = functools.reduce((lambda a, b: a + b), res)
        if cores is None: cores = mp.cpu_count()
        n_j_per_core = int(np.ceil(n / cores))
        JJ = []
        for i in range(0, n, n_j_per_core):
            JJ.append(Js[:, :, i:i+n_j_per_core])
        with mp.Pool(cores) as p:
            ret = p.starmap(transform_jacobian, zip(JJ, 
                        itertools.repeat(Qi), itertools.repeat(Qj)))
        ret = [np.transpose(r, axes=(2, 0, 1)) for r in ret]
        ret = np.transpose(np.vstack(ret), axes=(1, 2, 0))
    if return_J:
        return ret, Js
    else:
        return ret


def transform_jacobian(Js, Qi, Qj, pbar=False):
    d1, d2, n = Qi.shape[0], Qj.shape[0], Js.shape[2]
    ret = np.zeros((d1, d2, n))
    if pbar:
        iterj = tqdm(range(n), desc='Transforming subset Jacobian')
    else:
        iterj = range(n)
    for i in iterj:
        J = Js[:, :, i]
        ret[:, :, i] = Qi @ J @ Qj.T
    return ret


def vector_field_function_transformation(vf_func, Q):
    """Transform vector field function from PCA space to original space.
    The formula used for transformation:
                                            :math:`\hat{f} = f Q^T`,
    where `Q, f, \hat{f}` are the PCA loading matrix, low dimensional vector field function and the
    transformed high dimensional vector field function.

    Parameters
    ----------
        vf_func: `function`:
            The vector field function.
        Q: `np.ndarray`:
            PCA loading matrix with dimension d x k, where d is the dimension of the original space,
            and k the number of leading PCs.

    Returns
    -------
        ret `np.ndarray`
            The transformed vector field function.

    """
    return lambda x: vf_func.func(x) @ Q.T


def speed(adata,
          basis='umap',
          VecFld=None,
          method='analytical',
          ):
    """Calculate the speed for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        VecFld: `dict`
            The true ODE function, useful when the data is generated through simulation.
        method: `str` (default: `analytical`)
            The method that will be used for calculating speed, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating Jacobian. Otherwise,
            raw velocity vectors are used.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `speed` key in the .obs.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)

    X_data = adata.obsm["X_" + basis]

    vec_mat = func(X_data) if method == 'analytical' else adata.obsm["velocity_" + basis]
    speed = np.array([np.linalg.norm(i) for i in vec_mat])

    speed_key = "speed" if basis is None else "speed_" + basis

    adata.obs[speed_key] = speed


def jacobian(adata,
             regulators,
             effectors,
             basis='pca',
             VecFld=None,
             method='analytical',
             cores=1,
             ):
    """Calculate Jacobian for each cell with the reconstructed vector field function.

    If the vector field was reconstructed from the reduced PCA space, the Jacobian matrix will then be inverse
    transformed back to high dimension. Note that this should also be possible for reduced UMAP space and will be
    supported shortly. Note that we use analytical formula to calculate Jacobian matrix which computationally efficient.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        regulators: `list`
            The list of genes that will be used as regulators when calculating the cell-wise Jacobian matrix. The Jacobian
            is the matrix consisting of partial derivatives of the vector field wrt gene expressions. It can be used to 
            evaluate the change in velocities of effectors (see below) as the expressions of regulators increase. The 
            regulators are the denominators of the partial derivatives. 
        effectors: `List` or `None` (default: `None`)
            The list of genes that will be used as effectors when calculating the cell-wise Jacobian matrix. The effectors
            are the numerators of the partial derivatives.
        basis: `str` or None (default: `pca`)
            The embedding data in which the vector field was reconstructed. If `None`, use the vector field function that
            was reconstructed directly from the original unreduced gene expression space.
        VecFld: `dict`
            The true ODE (ordinary differential equations) function, useful when the data is generated through simulation
            with known ODE functions.
        method: `str` (default: `analytical`)
            The method that will be used for calculating Jacobian, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating Jacobian while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.
        cores: `int` (default: 1):
            Number of cores to calculate Jacobian. If cores is set to be > 1, multiprocessing will be used to
            parallel the Jacobian calculation.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `Jacobian` key in the .uns. This is a 3-dimensional tensor with
            dimensions n_obs x n_regulators x n_effectors.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)

    X, V = VecFld['X'], VecFld['V']

    cell_idx = np.arange(adata.n_obs)

    if type(regulators) == str: regulators = [regulators]
    if type(effectors) == str: effectors = [effectors]
    var_df = adata[:, adata.var.use_for_dynamics].var
    regulators = var_df.index.intersection(regulators)
    effectors = var_df.index.intersection(effectors)

    reg_idx, eff_idx = get_pd_row_column_idx(var_df, regulators, "row"), \
                             get_pd_row_column_idx(var_df, effectors, "row")
    if len(regulators) == 0 or len(effectors) == 0:
        raise ValueError(f"the source and target gene list you provided are not in the velocity gene list!")

    PCs_ = "PCs" if basis == 'pca' else "PCs_" + basis
    Jacobian_ = "jacobian" if basis is None else "jacobian_" + basis

    Q = adata.uns[PCs_][:, :X.shape[1]]

    if method == 'analytical':
        Jac_fun = lambda x: Jacobian_rkhs_gaussian(x, VecFld)
    elif method == 'numeric':
        Jac_fun = Jacobian_numerical(func, input_vector_convention='row')
    else:
        raise NotImplementedError(f"the Jacobian matrix calculation method {method} is not implemented. Currently only "
                                  f"support `analytical` and `numeric` methods.")

    if basis is None:
        Jacobian = Jac_fun(X)
    else:
        if len(regulators) == 1 and len(effectors) == 1:
            Jacobian, Js = elementwise_jacobian_transformation(Jac_fun, X[cell_idx], Q[eff_idx, :].flatten(),
                                                      Q[reg_idx, :].flatten(), True, timeit=True)
        else:
            Jacobian, Js = subset_jacobian_transformation(Jac_fun, X[cell_idx], Q[eff_idx, :],
                                                 Q[reg_idx, :], cores=cores, return_raw_J=True, timeit=True)

    adata.uns[Jacobian_] = {"Jacobian": Jacobian,
                            "Jacobian_raw": Js,
                            "source_gene": regulators,
                            "effectors": effectors,
                            "cell_idx": cell_idx}


def curl(adata,
         basis='umap',
         VecFld=None,
         method='analytical',
         ):
    """Calculate Curl for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        VecFld: `dict`
            The true ODE function, useful when the data is generated through simulation.
        method: `str` (default: `analytical`)
            The method that will be used for calculating divergence, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating curl while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `curl` key in the .obs.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)

    X_data = adata.obsm["X_" + basis][:, :2]

    curl = np.zeros((adata.n_obs, 1))

    Jacobian_ = "jacobian" if basis is None else "jacobian_" + basis

    if Jacobian_ in adata.uns_keys():
        Js = adata.uns[Jacobian_]['Jacobian_raw']
        for i in tqdm(range(X_data.shape[0]), f"Calculating curl with the reconstructed vector field on the {basis} basis. "):
            curl[i] = curl2d(func, None, method=method, VecFld=None, jac=Js[:, :, i])
    else:
        for i, x in tqdm(enumerate(X_data), f"Calculating curl with the reconstructed vector field on the {basis} basis. "):
            curl[i] = curl2d(func, x.flatten(), method=method, VecFld=VecFld)

    curl_key = "curl" if basis is None else "curl_" + basis

    adata.obs[curl_key] = curl


def divergence(adata,
               cell_idx=None,
               sampling=None,
               sample_ncells=1000,
               basis='pca',
               vector_field_class=None,
               method='analytical',
               store_in_adata=True,
               **kwargs
               ):
    """Calculate divergence for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        vector_field_class: :class:`~scVectorField.vectorfield`
            If not None, the divergene will be computed using this class instead of the vector field stored in adata.
        method: `str` (default: `analytical`)
            The method that will be used for calculating divergence, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating Jacobian while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `divergence` key in the .obs.
    """

    if vector_field_class is None:
        vector_field_class = vectorfield()
        vector_field_class.from_adata(adata, basis=basis)

    if basis == 'umap': cell_idx = np.arange(adata.n_obs)

    X = vector_field_class.get_X()
    if cell_idx is None:
        if sampling is None or sampling == 'all':
            cell_idx = np.arange(adata.n_obs)
        elif sampling == 'random':
            cell_idx = np.random.choice(np.arange(adata.n_obs), size=sample_ncells, replace=False)
        elif sampling == 'velocity':
            cell_idx = sample_by_velocity(vector_field_class.get_V(), sample_ncells)
        elif sampling == 'trn':
            cell_idx = trn(X, sample_ncells)
        else:
            raise NotImplementedError(f"The sampling method {sampling} is not implemented. Currently only support velocity "
                                      f"based (velocity) or topology representing network (trn) based sampling.")

    jkey = "jacobian" if basis is None else "jacobian_" + basis

    div = np.zeros(len(cell_idx))
    calculated = np.zeros(len(cell_idx), dtype=bool)
    if jkey in adata.uns_keys():
        Js = adata.uns[jkey]['Jacobian_raw']
        cidx = adata.uns[jkey]['cell_idx']
        for i, c in tqdm(enumerate(cell_idx), desc="Calculating divergence with precomputed Jacobians"):
            if c in cidx:
                calculated[i] = True
                div[i] = np.trace(Js[:, :, i]) if Js.shape[2] == len(cell_idx) else np.trace(Js[:, :, c])

    div[~calculated] = vector_field_class.compute_divergence(X[cell_idx[~calculated]], **kwargs)

    if store_in_adata:
        div_key = "divergence" if basis is None else "divergence_" + basis
        Div = adata.obs[div_key] if div_key in adata.obs.keys() else np.ones(adata.n_obs) * np.nan
        Div[cell_idx] = div
        adata.obs[div_key] = Div
    return div


def acceleration(adata,
         basis='umap',
         VecFld=None,
         method='analytical',
         ):
    """Calculate acceleration for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        VecFld: `dict`
            The true ODE function, useful when the data is generated through simulation.
        method: `str` (default: `analytical`)
            The method that will be used for calculating divergence, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating acceleration while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `acceleration` key in the .obs as well as .obsm. If basis is `pca`,
            acceleration matrix will be inverse transformed back to original high dimension space.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)
    f_jac = lambda x: Jacobian_rkhs_gaussian(x, VecFld) if method == 'analytical' else Jacobian_numerical(func)

    X_data = adata.obsm["X_" + basis]

    acce_mat = compute_acceleration(func, f_jac, X_data, return_all=False)
    acce = np.array([np.linalg.norm(i) for i in acce_mat])

    acce_key = "acceleration" if basis is None else "acceleration_" + basis

    adata.obs[acce_key] = acce
    adata.obsm[acce_key] = acce_mat

    if basis == 'pca':
        adata.layers['acceleration'] = adata.layers['velocity_S'].copy()
        adata.layers['acceleration'][:, np.where(adata.var.use_for_dynamics)[0]] = acce_mat @ adata.uns['PCs'].T


def curvature(adata,
         basis='umap',
         VecFld=None,
         method='analytical',
         ):
    """Calculate curvature for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        VecFld: `dict`
            The true ODE function, useful when the data is generated through simulation.
        method: `str` (default: `analytical`)
            The method that will be used for calculating divergence, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating curvature while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `curvature` key in the .obs.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)
    f_jac = lambda x: Jacobian_rkhs_gaussian(x, VecFld) if method == 'analytical' else Jacobian_numerical(func)

    X_data = adata.obsm["X_" + basis]

    curv = compute_curvature(func, f_jac, X_data)

    curv_key = "curvature" if basis is None else "curvature_" + basis

    adata.obs[curv_key] = curv


def torsion(adata,
         basis='umap',
         VecFld=None,
         method='analytical',
         ):
    """Calculate torsion for each cell with the reconstructed vector field function.

    Parameters
    ----------
        adata: :class:`~anndata.AnnData`
            AnnData object that contains the reconstructed vector field function in the `uns` attribute.
        basis: `str` or None (default: `umap`)
            The embedding data in which the vector field was reconstructed.
        VecFld: `dict`
            The true ODE function, useful when the data is generated through simulation.
        method: `str` (default: `analytical`)
            The method that will be used for calculating divergence, either `analytical` or `numeric`. `analytical`
            method will use the analytical form of the reconstructed vector field for calculating torsion while
            `numeric` method will use numdifftools for calculation. `analytical` method is much more efficient.

    Returns
    -------
        adata: :class:`~anndata.AnnData`
            AnnData object that is updated with the `torsion` key in the .obs.
    """

    if VecFld is None:
        VecFld, func = vecfld_from_adata(adata, basis)
    else:
        func = lambda x: vector_field_function(x, VecFld)
    f_jac = lambda x: Jacobian_rkhs_gaussian(x, VecFld) if method == 'analytical' else Jacobian_numerical(func)

    X_data = adata.obsm["X_" + basis]

    torsion_mat = compute_torsion(func, f_jac, X_data)
    torsion = np.array([np.linalg.norm(i) for i in torsion_mat])

    torsion_key = "torsion" if basis is None else "torsion_" + basis

    adata.obs[torsion_key] = torsion
    adata.uns[torsion_key] = torsion_mat

