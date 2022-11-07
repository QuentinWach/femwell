"""Waveguide analysis based on https://doi.org/10.1080/02726340290084012."""
import matplotlib.pyplot as plt
import numpy as np
import scipy.sparse.linalg

from skfem import BilinearForm, Basis, ElementTriN0, ElementTriP0, ElementTriP1, ElementVector, Mesh, condense, solve, solver_eigen_scipy_sym, solver_eigen_slepc
from skfem.helpers import curl, grad, dot, inner


def compute_modes(basis_epsilon_r, epsilon_r, wavelength, mu_r, num_modes):
    k0 = 2 * np.pi / wavelength

    basis = basis_epsilon_r.with_element(ElementTriN0() * ElementTriP1())

    @BilinearForm(dtype=epsilon_r.dtype)
    def aform(e_t, e_z, v_t, v_z, w):
        return 1 / mu_r * curl(e_t) * curl(v_t) \
               - k0 ** 2 * w['epsilon'] * dot(e_t, v_t) \
               - 1 / mu_r * dot(grad(e_z), v_t) \
               + w['epsilon'] * inner(e_t, grad(v_z)) + w['epsilon'] * e_z * v_z

    @BilinearForm(dtype=epsilon_r.dtype)
    def bform(e_t, e_z, v_t, v_z, w):
        return - 1 / mu_r * dot(e_t, v_t)

    A = aform.assemble(basis, epsilon=basis_epsilon_r.interpolate(epsilon_r))
    B = bform.assemble(basis, epsilon=basis_epsilon_r.interpolate(epsilon_r))

    # lams, xs = solve(*condense(A, B, D=basis.get_dofs()),
    #                solver=solver_eigen_scipy_sym(k=10, sigma=k0 ** 2 * 2.5 ** 2))
    from petsc4py import PETSc
    from slepc4py import SLEPc

    A_ = PETSc.Mat().createAIJ(size=A.shape, csr=(A.indptr, A.indices, A.data))
    B_ = PETSc.Mat().createAIJ(size=B.shape, csr=(B.indptr, B.indices, B.data))

    eps = SLEPc.EPS().create()
    eps.setOperators(A_, B_)
    eps.getST().setType(SLEPc.ST.Type.SINVERT)
    eps.setWhichEigenpairs(SLEPc.EPS.Which.TARGET_MAGNITUDE)
    eps.setTarget(k0 ** 2 * np.max(epsilon_r) ** 2)
    eps.setDimensions(num_modes)
    # eps.setTolerances(1e-8)
    eps.solve()

    xr, xi = A_.getVecs()
    lams, xs = [], []
    for i in range(eps.getConverged()):
        lams.append(eps.getEigenpair(i, xr, xi))
        xs.append(np.array(xr) + 1j * np.array(xi))

    xs = np.array(xs)
    lams = np.array(lams)
    xs[:, basis.split_indices()[1]] /= np.sqrt(lams[:, np.newaxis])  # undo the scaling E_3,new = beta * E_3

    return np.sqrt(lams) / k0, basis, xs


def calculate_hfield(basis, xs, beta):
    xs = xs.astype(complex)
    print(xs.dtype)

    @BilinearForm
    def aform(e_t, e_z, v_t, v_z, w):
        return (-1j * e_t[1] + e_z.grad[1]) * v_t[1] + (1j * beta * e_t[0] - e_z.grad[0]) * v_t[0]
        # return e_t.curl * v_z

    a_operator = aform.assemble(basis)
    print(basis.quadrature)
    print(a_operator.shape)

    @BilinearForm
    def bform(e_t, e_z, v_t, v_z, w):
        return dot(e_t, v_t) + e_z * v_z

    b_operator = bform.assemble(basis)

    return scipy.sparse.linalg.spsolve(b_operator, a_operator @ xs)


def plot_mode(basis, mode, plot_vectors=False, colorbar=True):
    mode = np.real(mode)
    (et, et_basis), (ez, ez_basis) = basis.split(mode)

    if plot_vectors:
        fig, axs = plt.subplots(1, 2)
        et_basis.plot(et, ax=axs[0])
        ez_basis.plot(ez, ax=axs[1], colorbar=True)
        return fig, axs

    plot_basis = et_basis.with_element(ElementVector(ElementTriP0()))
    et_xy = plot_basis.project(et_basis.interpolate(et))
    (et_x, et_x_basis), (et_y, et_y_basis) = plot_basis.split(et_xy)

    fig, axs = plt.subplots(1, 3)
    for ax in axs:
        ax.set_aspect(1)

    cbar = ({'colorbar': colorbar} if colorbar is not False else {})
    et_x_basis.plot(et_x, shading='gouraud', ax=axs[0], **cbar)  # , vmin=np.min(mode), vmax=np.max(mode))
    et_y_basis.plot(et_y, shading='gouraud', ax=axs[1], **cbar)  # , vmin=np.min(mode), vmax=np.max(mode))
    ez_basis.plot(ez, shading='gouraud', ax=axs[2], **cbar)  # , vmin=np.min(mode), vmax=np.max(mode))
    plt.tight_layout()

    return fig, axs


if __name__ == "__main__":
    mesh = Mesh.load('mesh.msh')
    basis0 = Basis(mesh, ElementTriP0(), intorder=4)
    epsilon = basis0.zeros(dtype=complex)
    epsilon[basis0.get_dofs(elements='core')] = 3.4777 ** 2
    epsilon[basis0.get_dofs(elements='core2')] = 3.5777 ** 2
    epsilon[basis0.get_dofs(elements='clad')] = 1.444 ** 2
    epsilon[basis0.get_dofs(elements='box')] = 1.444 ** 2
    # basis0.plot(epsilon, colorbar=True).show()

    lams, basis, xs = compute_modes(basis0, epsilon, wavelength=1.55, mu_r=1, num_modes=1)

    print(lams)

    plot_mode(basis, np.real(xs[0]))
    plt.show()

    xbs = calculate_hfield(basis, xs[0], (lams[0] * (2 * np.pi / 1.55)) ** 2)

    plot_mode(basis, np.real(xbs))
    plt.show()
    plot_mode(basis, np.imag(xbs))
    plt.show()
