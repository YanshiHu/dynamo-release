import numpy as np
from scipy.spatial.distance import cdist
from tqdm import tqdm
import numdifftools as nd
from multiprocessing.dummy import Pool as ThreadPool
import multiprocessing as mp
import itertools, functools
from .utils import timeit


def grad(f, x):
    """Gradient of scalar-valued function f evaluated at x"""
    return nd.Gradient(f)(x)


def laplacian(f, x):
    """Laplacian of scalar field f evaluated at x"""
    hes = nd.Hessdiag(f)(x)
    return sum(hes)


@timeit
def vector_field_function(x, vf_dict, dim=None, kernel='full', **kernel_kwargs):
    """vector field function constructed by sparseVFC.
    Reference: Regularized vector field learning with sparse approximation for mismatch removal, Ma, Jiayi, etc. al, Pattern Recognition
    """
    # x=np.array(x).reshape((1, -1))
    if "div_cur_free_kernels" in vf_dict.keys():
        has_div_cur_free_kernels = True
    else:
        has_div_cur_free_kernels = False

    #x = np.array(x)
    if x.ndim == 1:
        x = x[None, :]

    if has_div_cur_free_kernels:
        if kernel == 'full':
            kernel_ind = 0
        elif kernel == 'df_kernel':
            kernel_ind = 1
        elif kernel == 'cf_kernel':
            kernel_ind = 2
        else:
            raise ValueError(f"the kernel can only be one of {'full', 'df_kernel', 'cf_kernel'}!")

        K = con_K_div_cur_free(x, vf_dict["X_ctrl"], vf_dict["sigma"], vf_dict["eta"], **kernel_kwargs)[kernel_ind]
    else:
        K = con_K(x, vf_dict["X_ctrl"], vf_dict["beta"], **kernel_kwargs)

    if dim is None or has_div_cur_free_kernels:
        K = K.dot(vf_dict["C"])
    else:
        K = K.dot(vf_dict["C"][:, dim])
    return K


@timeit
def con_K(x, y, beta, method='cdist', return_d=False):
    """con_K constructs the kernel K, where K(i, j) = k(x, y) = exp(-beta * ||x - y||^2).

    Arguments
    ---------
        x: :class:`~numpy.ndarray`
            Original training data points.
        y: :class:`~numpy.ndarray`
            Control points used to build kernel basis functions.
        beta: float (default: 0.1)
            Paramerter of Gaussian Kernel, k(x, y) = exp(-beta*||x-y||^2),
        return_d: bool
            If True the intermediate 3D matrix x - y will be returned for analytical Jacobian.

    Returns
    -------
    K: 'np.ndarray'
    the kernel to represent the vector field function.
    """
    if method == 'cdist' and not return_d:
        K = cdist(x, y, 'sqeuclidean')
        if len(K) == 1:
            K = K.flatten()
    else:
        n = x.shape[0]
        m = y.shape[0]

        # https://stackoverflow.com/questions/1721802/what-is-the-equivalent-of-matlabs-repmat-in-numpy
        # https://stackoverflow.com/questions/12787475/matlabs-permute-in-python
        D = np.matlib.tile(x[:, :, None], [1, 1, m]) - np.transpose(
            np.matlib.tile(y[:, :, None], [1, 1, n]), [2, 1, 0])
        K = np.squeeze(np.sum(D ** 2, 1))
    K = -beta * K
    K = np.exp(K)

    if return_d:
        return K, D
    else:
        return K


@timeit
def con_K_div_cur_free(x, y, sigma=0.8, eta=0.5):
    """Construct a convex combination of the divergence-free kernel T_df and curl-free kernel T_cf with a bandwidth sigma
    and a combination coefficient gamma.

    Arguments
    ---------
        x: 'np.ndarray'
            Original training data points.
        y: 'np.ndarray'
            Control points used to build kernel basis functions
        sigma: 'int' (default: `0.8`)
            Bandwidth parameter.
        eta: 'int' (default: `0.5`)
            Combination coefficient for the divergence-free or the curl-free kernels.

    Returns
    -------
        A tuple of G (the combined kernel function), divergence-free kernel and curl-free kernel.

    See also:: :func:`sparseVFC`.
    """
    m, d = x.shape
    n, d = y.shape
    sigma2 = sigma ** 2
    G_tmp = np.matlib.tile(x[:, :, None], [1, 1, n]) - np.transpose(
        np.matlib.tile(y[:, :, None], [1, 1, m]), [2, 1, 0]
    )
    G_tmp = np.squeeze(np.sum(G_tmp ** 2, 1))
    G_tmp3 = -G_tmp / sigma2
    G_tmp = -G_tmp / (2 * sigma2)
    G_tmp = np.exp(G_tmp) / sigma2
    G_tmp = np.kron(G_tmp, np.ones((d, d)))

    x_tmp = np.matlib.tile(x, [n, 1])
    y_tmp = np.matlib.tile(y, [1, m]).T
    y_tmp = y_tmp.reshape((d, m * n), order='F').T
    xminusy = x_tmp - y_tmp
    G_tmp2 = np.zeros((d * m, d * n))

    tmp4_ = np.zeros((d, d))
    for i in tqdm(range(d), desc="Iterating each dimension in con_K_div_cur_free:"):
        for j in np.arange(i, d):
            tmp1 = xminusy[:, i].reshape((m, n), order='F')
            tmp2 = xminusy[:, j].reshape((m, n), order='F')
            tmp3 = tmp1 * tmp2
            tmp4 = tmp4_.copy()
            tmp4[i, j] = 1
            tmp4[j, i] = 1
            G_tmp2 = G_tmp2 + np.kron(tmp3, tmp4)

    G_tmp2 = G_tmp2 / sigma2
    G_tmp3 = np.kron((G_tmp3 + d - 1), np.eye(d))
    G_tmp4 = np.kron(np.ones((m, n)), np.eye(d)) - G_tmp2
    df_kernel, cf_kernel = (1 - eta) * G_tmp * (G_tmp2 + G_tmp3), eta * G_tmp * G_tmp4
    G = df_kernel + cf_kernel

    return G, df_kernel, cf_kernel


def vecfld_from_adata(adata, basis='', vf_key='VecFld'):
    if basis is not None or len(basis) > 0:
        vf_key = '%s_%s' % (vf_key, basis)

    if vf_key not in adata.uns.keys():
        raise ValueError(
            f'Vector field function {vf_key} is not included in the adata object! '
            f"Try firstly running dyn.tl.VectorField(adata, basis='{basis}')")
        
    vf_dict = adata.uns[vf_key]['VecFld']
    func = lambda x: vector_field_function(x, vf_dict)

    return vf_dict, func


def Jacobian_rkhs_gaussian(x, vf_dict, vectorize=False):
    """analytical Jacobian for RKHS vector field functions with Gaussian kernel.

        Arguments
        ---------
        x: :class:`~numpy.ndarray`
            Coordinates where the Jacobian is evaluated.
        vf_dict: dict
            A dictionary containing RKHS vector field control points, Gaussian bandwidth,
            and RKHS coefficients.
            Essential keys: 'X_ctrl', 'beta', 'C'

        Returns
        -------
        J: :class:`~numpy.ndarray`
            Jacobian matrices stored as d-by-d-by-n numpy arrays evaluated at x.
            d is the number of dimensions and n the number of coordinates in x.
    """
    if x.ndim == 1: 
        K, D = con_K(x[None, :], vf_dict['X_ctrl'], vf_dict['beta'], return_d=True)
        J = (vf_dict['C'].T * K) @ D[0].T
    elif not vectorize:
        n, d = x.shape
        J = np.zeros((d, d, n))
        for i, xi in enumerate(x):
            K, D = con_K(xi[None, :], vf_dict['X_ctrl'], vf_dict['beta'], return_d=True)
            J[:, :, i] = (vf_dict['C'].T * K) @ D[0].T
    else:
        K, D = con_K(x, vf_dict['X_ctrl'], vf_dict['beta'], return_d=True)
        if K.ndim == 1: K = K[None, :]
        J = np.einsum('nm, mi, njm -> ijn', K, vf_dict['C'], D)

    return -2 * vf_dict['beta'] * J


def Jacobian_rkhs_gaussian_parallel(x, vf_dict, cores=None):
    n = len(x)
    if cores is None: cores = mp.cpu_count()
    n_j_per_core = int(np.ceil(n / cores))
    xx = []
    for i in range(0, n, n_j_per_core):
        xx.append(x[i:i+n_j_per_core])
    #with mp.Pool(cores) as p:
    #    ret = p.starmap(Jacobian_rkhs_gaussian, zip(xx, itertools.repeat(vf_dict)))
    with ThreadPool(cores) as p:
        ret = p.starmap(Jacobian_rkhs_gaussian, zip(xx, itertools.repeat(vf_dict)))
    ret = [np.transpose(r, axes=(2, 0, 1)) for r in ret]
    ret = np.transpose(np.vstack(ret), axes=(1, 2, 0))
    return ret


def Jacobian_numerical(f, input_vector_convention='row'):
    '''
        Get the numerical Jacobian of the vector field function.
        If the input_vector_convention is 'row', it means that fjac takes row vectors
        as input, otherwise the input should be an array of column vectors. Note that
        the returned Jacobian would behave exactly the same if the input is an 1d array.

        The column vector convention is slightly faster than the row vector convention.
        So the matrix of row vector convention is converted into column vector convention
        under the hood.

        No matter the input vector convention, the returned Jacobian is of the following
        format:
                df_1/dx_1   df_1/dx_2   df_1/dx_3   ...
                df_2/dx_1   df_2/dx_2   df_2/dx_3   ...
                df_3/dx_1   df_3/dx_2   df_3/dx_3   ...
                ...         ...         ...         ...
    '''
    fjac = nd.Jacobian(lambda x: f(x.T).T)
    if input_vector_convention == 'row' or input_vector_convention == 0:
        def f_aux(x):
            x = x.T
            return fjac(x)

        return f_aux
    else:
        return fjac


def _divergence(f, x):
    """Divergence of the reconstructed vector field function f evaluated at x"""
    jac = nd.Jacobian(f)(x)
    return np.trace(jac)

 
@timeit
def compute_divergence(f_jac, X, vectorize_size=1):
    """Calculate divergence for many samples by taking the trace of a Jacobian matrix.

    vectorize_size is used to control the number of samples computed in each vectorized batch.
        If vectorize_size = 1, there's no vectorization whatsoever.
        If vectorize_size = None, all samples are vectorized.
    """
    n = len(X)
    if vectorize_size is None: vectorize_size = n

    div = np.zeros(n)
    for i in tqdm(range(0, n, vectorize_size), desc="Calculating divergence"):
        J = f_jac(X[i:i+vectorize_size])
        div[i:i+vectorize_size] = np.trace(J)
    return div


def acceleration_(v, J):
    return J.dot(v[:, None]) if v.ndim == 1 else J.dot(v)


def curvature_(a, v):
    kappa = np.linalg.norm(np.outer(v[:, None], a)) / np.linalg.norm(v)**3 if v.ndim == 1 else \
        np.linalg.norm(v.outer(a)) / np.linalg.norm(v)**3

    return kappa


def torsion_(v, J, a):
    """only works in 3D"""
    tau = np.outer(v[:, None], a).dot(J.dot(a)) / np.linalg.norm(np.outer(v[:, None], a))**2 if v.ndim == 1 else \
        np.outer(v, a).dot(J.dot(a)) / np.linalg.norm(np.outer(v, a))**2

    return tau


@timeit
def compute_acceleration(vf, f_jac, X, return_all=False):
    """Calculate acceleration for many samples via

    .. math::
    a = J \cdot v.

    """
    n = len(X)
    acce = np.zeros((n, X.shape[1]))

    v_ = vf(X)
    J_ = f_jac(X)
    for i in tqdm(range(n), desc=f"Calculating acceleration"):
        v = v_[i]
        J = J_[:, :, i]
        acce[i] = acceleration_(v, J).flatten()

    if return_all:
        return v_, J_, acce
    else:
        return acce


@timeit
def compute_curvature(vf, f_jac, X):
    """Calculate curvature for many samples via

    .. math::
    \kappa = \frac{||\mathbf{v} \times \mathbf{a}||}{||\mathbf{V}||^3}
    """
    n = len(X)

    curv = np.zeros(n)
    v, _, a = compute_acceleration(vf, f_jac, X, return_all=True)

    for i in tqdm(range(n), desc="Calculating curvature"):
        curv[i] = curvature_(a[i], v[i])

    return curv


@timeit
def compute_torsion(vf, f_jac, X):
    """Calculate torsion for many samples via

    .. math::
    \tau = \frac{(\mathbf{v} \times \mathbf{a}) \cdot (\mathbf{J} \cdot \mathbf{a})}{||\mathbf{V} \times \mathbf{a}||^2}
    """
    if X.shape[1] != 3:
        raise Exception(f'torsion is only defined in 3 dimension.')

    n = len(X)

    tor = np.zeros((n, X.shape[1], X.shape[1]))
    v, J, a = compute_acceleration(vf, f_jac, X, return_all=True)

    for i in tqdm(range(n), desc="Calculating torsion"):
        tor[i] = torsion_(v[i], J[:, :, i], a[i])

    return tor


def _curl(f, x, method='analytical', VecFld=None, jac=None):
    """Curl of the reconstructed vector field f evaluated at x in 3D"""
    if jac is None:
        if method == 'analytical' and VecFld is not None:
            jac = Jacobian_rkhs_gaussian(x, VecFld)
        else:
            jac = nd.Jacobian(f)(x)

    return np.array([jac[2, 1] - jac[1, 2], jac[0, 2] - jac[2, 0], jac[1, 0] - jac[0, 1]])


def curl2d(f, x, method='analytical', VecFld=None, jac=None):
    """Curl of the reconstructed vector field f evaluated at x in 2D"""
    if jac is None:
        if method == 'analytical' and VecFld is not None:
            jac = Jacobian_rkhs_gaussian(x, VecFld)
        else:
            jac = nd.Jacobian(f)(x)

    curl = jac[1, 0] - jac[0, 1]

    return curl

@timeit
def compute_curl(f_jac, X):
    """Calculate curl for many samples for 2/3 D systems.
    """
    if X.shape[1] > 3:
        raise Exception(f'curl is only defined in 2/3 dimension.')

    n = len(X)

    if X.shape[1] == 2:
        curl = np.zeros(n)
        f = curl2d
    else:
        curl = np.zeros((n, 2, 2))
        f = _curl

    for i in tqdm(range(n), desc=f"Calculating {X.shape[1]}-D curl"):
        J = f_jac(X[i])
        curl[i] = f(None, None, method='analytical', VecFld=None, jac=J)

    return curl