"""This module defines the three subproblems:

  FluidProblem     - the fluid problem (F)
  StructureProblem - the structure problem (S)
  MeshProblem      - the mesh problem (M)
"""

__author__ = "Kristoffer Selim and Anders Logg"
__copyright__ = "Copyright (C) 2010 Simula Research Laboratory and %s" % __author__
__license__  = "GNU GPL Version 3 or any later version"

# Last changed: 2011-02-18

__all__ = ["FluidProblem", "StructureProblem", "MeshProblem", "extract_solution",
           "extract_num_dofs"]

from dolfin import *

from cbc.flow import NavierStokes
from cbc.twist import Hyperelasticity, StVenantKirchhoff
from cbc.twist import DeformationGradient, PiolaTransform

# Define fluid problem
class FluidProblem(NavierStokes):

    def __init__(self, problem):

        # Store problem
        self.problem = problem

        # Store initial and current mesh
        self.Omega_F = problem.fluid_mesh()
        self.omega_F0 = Mesh(self.Omega_F)
        self.omega_F1 = Mesh(self.Omega_F)

        # Create functions for velocity and pressure on reference domain
        self.V = VectorFunctionSpace(self.Omega_F, "CG", 2)
        self.Q = FunctionSpace(self.Omega_F, "CG", 1)
        self.U_F = Function(self.V)
        self.P_F = Function(self.Q)

        # Calculate number of dofs
        self.num_dofs = self.U_F.vector().size() + self.P_F.vector().size()

        # Initialize base class
        NavierStokes.__init__(self)

        # Don't plot and save solution in subsolvers
        self.parameters["solver_parameters"]["plot_solution"] = False
        self.parameters["solver_parameters"]["save_solution"] = False

    def mesh(self):
        return self.omega_F1

    def viscosity(self):
        return self.problem.fluid_viscosity()

    def density(self):
        return self.problem.fluid_density()

    def mesh_velocity(self, V):
        self.w = Function(V)
        return self.w

    def velocity_dirichlet_values(self):
        return self.problem.fluid_velocity_dirichlet_values()

    def velocity_dirichlet_boundaries(self):
        return self.problem.fluid_velocity_dirichlet_boundaries()

    def pressure_dirichlet_values(self):
        return self.problem.fluid_pressure_dirichlet_values()

    def pressure_dirichlet_boundaries(self):
        return self.problem.fluid_pressure_dirichlet_boundaries()

    def velocity_initial_condition(self):
        return self.problem.fluid_velocity_initial_condition()

    def pressure_initial_condition(self):
        return self.problem.fluid_pressure_initial_condition()

    def end_time(self):
        return self.problem.end_time()

    def time_step(self):
        # Time step will be selected elsewhere
        return self.end_time()

    def compute_fluid_stress(self, u_F, p_F, U_M):

        # Map u and p back to reference domain
        self.U_F.vector()[:] = u_F.vector()[:]
        self.P_F.vector()[:] = p_F.vector()[:]

        # Compute mesh deformation gradient
        F = DeformationGradient(U_M)
        F_inv = inv(F)
        F_inv_T = F_inv.T
        I = variable(Identity(U_M.cell().d))

        # Compute mapped stress sigma_F \circ Phi (here, grad "=" Grad)
        mu = self.viscosity()
        sigma_F = mu*(grad(self.U_F)*F_inv + F_inv_T*grad(self.U_F).T) - self.P_F*I

        # Map to physical stress
        Sigma_F = PiolaTransform(sigma_F, U_M)

        return Sigma_F

    def update_mesh_displacement(self, U_M, dt, num_smoothings):

        # Get mesh coordinate data
        X  = self.Omega_F.coordinates()
        x0 = self.omega_F0.coordinates()
        x1 = self.omega_F1.coordinates()
        dofs = U_M.vector().array()
        dim = self.omega_F1.geometry().dim()
        N = self.omega_F1.num_vertices()

        # Update omega_F1
        for i in range(N):
            for j in range(dim):
                x1[i][j] = X[i][j] + dofs[j*N + i]

        # Smooth the mesh
        self.omega_F1.smooth(num_smoothings)

        # Update mesh velocity
        wx = self.w.vector().array()
        for i in range(N):
            for j in range(dim):
                wx[j*N + i] = (x1[i][j] - x0[i][j]) / dt

        # Update vector values (necessary since wx is a copy)
        self.w.vector()[:] = wx

        # Reassemble matrices
        self.solver.reassemble()

    def update_extra(self):

        # Copy mesh coordinates
        self.omega_F0.coordinates()[:] = self.omega_F1.coordinates()[:]

    def __str__(self):
        return "The fluid problem (F)"

# Define structure problem
class StructureProblem(Hyperelasticity):

    def __init__(self, problem, parameters):

        # Store problem
        self.problem = problem

        # Define function spaces and functions for transfer of fluid stress
        structure_element_degree = parameters["structure_element_degree"]
        Omega_F = problem.fluid_mesh()
        Omega_S = problem.structure_mesh()
        self.V_F = VectorFunctionSpace(Omega_F, "CG", structure_element_degree)
        self.V_S = VectorFunctionSpace(Omega_S, "CG", structure_element_degree)
        self.test_F = TestFunction(self.V_F)
        self.trial_F = TrialFunction(self.V_F)
        self.G_F = Function(self.V_F)
        self.G_S = Function(self.V_S)
        self.N_F = FacetNormal(Omega_F)
        self.N_S = FacetNormal(Omega_S)

        # Calculate number of dofs
        self.num_dofs = 2 * self.G_S.vector().size()

        # Initialize base class
        Hyperelasticity.__init__(self)

        # Don't plot and save solution in subsolvers
        self.parameters["solver_parameters"]["plot_solution"] = False
        self.parameters["solver_parameters"]["save_solution"] = False
        self.parameters["solver_parameters"]["element_degree"] = parameters["structure_element_degree"]

    def mesh(self):
        return self.problem.structure_mesh()

    def reference_density(self):
        return self.problem.structure_density()

    def dirichlet_values(self):
        return self.problem.structure_dirichlet_values()

    def dirichlet_boundaries(self):
        return self.problem.structure_dirichlet_boundaries()

    def neumann_boundaries(self):
        return [self.problem.structure_neumann_boundaries()]

    def neumann_conditions(self):
        return [self.G_S]

    def material_model(self):
        mu    = self.problem.structure_mu()
        lmbda = self.problem.structure_lmbda()
        return StVenantKirchhoff([mu, lmbda])

    def update_fluid_stress(self, Sigma_F):

        # Project traction to a function on the boundary. This ensures
        # that the integral of G_S inside the structure solver equals
        # the integral of G_F since G_F and G_S are set equal on the
        # common boundary, dof by dof. Furthermore, the integral of
        # G_F against a test function is by the below projection equal
        # to the integral of the tracion Sigma_F N_F so this transfer
        # in fact does not involve an approximation.
        info("Assembling traction on fluid domain")
        new = True
        if new:
            d_FSI = ds(2)
            a_F = dot(self.test_F, self.trial_F)*d_FSI
            L_F = -dot(self.test_F, dot(Sigma_F, self.N_F))*d_FSI
            A_F = assemble(a_F, exterior_facet_domains=self.problem.fsi_boundary_F)
            B_F = assemble(L_F, exterior_facet_domains=self.problem.fsi_boundary_F)
        else:
            a_F = dot(self.test_F, self.trial_F)*ds
            L_F = -dot(self.test_F, dot(Sigma_F, self.N_F))*ds
            A_F = assemble(a_F)
            B_F = assemble(L_F)
        A_F.ident_zeros()
        solve(A_F, self.G_F.vector(), B_F)

        # Add contribution from fluid vector to structure
        info("Transferring values to structure domain")
        self.G_S.vector().zero()
        self.problem.add_f2s(self.G_S.vector(), self.G_F.vector())

        # Uncomment to debug transfer of stress
        #self.debug_stress_transfer(Sigma_F)

    def time_stepping(self):
        return "CG1"

    def time_step(self):
        # Time step will be selected elsewhere
        return self.end_time()

    def end_time(self):
        return self.problem.end_time()

    def debug_stress_transfer(self, Sigma_F):
        "Debug transfer of stress"

        d_FSI = ds(2)

        # Compute direct integral of normal traction
        form = dot(dot(Sigma_F, self.N_F), self.N_F)*d_FSI
        integral_0 = assemble(form, exterior_facet_domains=self.problem.fsi_boundary_F)

        # Compute integral of projected (and negated) normal traction
        form = dot(self.G_F, self.N_F)*d_FSI
        integral_1 = -assemble(form, exterior_facet_domains=self.problem.fsi_boundary_F)

        # Compute integral of transferred projection
        form = dot(self.G_S, self.N_S)*d_FSI
        integral_2 = assemble(form, exterior_facet_domains=self.problem.fsi_boundary_S)

        info("Debugging transfer of stress from fluid to structure.")
        info("The following three integrals should be the same")
        info("")
        info("  I0 = %.16g" % integral_0)
        info("  I1 = %.16g" % integral_1)
        info("  I2 = %.16g" % integral_2)
        info("")

    def __str__(self):
        return "The structure problem (S)"

# Define mesh problem (time-dependent linear elasticity)
class MeshProblem():

    def __init__(self, problem, parameters):

        # Store problem
        self.problem = problem

        # Get problem parameters
        mu = problem.mesh_mu()
        lmbda = problem.mesh_lmbda()
        alpha = problem.mesh_alpha()
        Omega_F = problem.fluid_mesh()

        # Define function spaces and functions
        V = VectorFunctionSpace(Omega_F, "CG", 1)
        v = TestFunction(V)
        u = TrialFunction(V)
        u0 = Function(V)
        u1 = Function(V)

        # Calculate number of dofs
        self.num_dofs = u0.vector().size()

        # Define boundary condition
        structure_element_degree = parameters["structure_element_degree"]
        W = VectorFunctionSpace(Omega_F, "CG", structure_element_degree)
        displacement = Function(W)
        bc = DirichletBC(V, displacement, DomainBoundary())

        # Define the stress tensor
        def sigma(v):
            return 2.0*mu*sym(grad(v)) + lmbda*tr(grad(v))*Identity(v.cell().d)

        # Define cG(1) scheme for time-stepping
        k = Constant(0)
        a = alpha*inner(v, u)*dx + 0.5*k*inner(sym(grad(v)), sigma(u))*dx
        L = alpha*inner(v, u0)*dx - 0.5*k*inner(sym(grad(v)), sigma(u0))*dx

        # Store variables for time stepping
        self.u0 = u0
        self.u1 = u1
        self.a = a
        self.L = L
        self.k = k
        self.displacement = displacement
        self.bc = bc

    def step(self, dt):
        "Compute solution for new time step"

        # Update time step
        self.k.assign(dt)

        # Assemble linear system and apply boundary conditions
        A = assemble(self.a)
        b = assemble(self.L)
        self.bc.apply(A, b)

        # Compute solution
        solve(A, self.u1.vector(), b)

        return self.u1

    def update(self, t):
        self.u0.assign(self.u1)
        return self.u1

    def update_structure_displacement(self, U_S):
        self.displacement.vector().zero()
        self.problem.add_s2f(self.displacement.vector(), U_S.vector())

    def solution(self):
        "Return current solution values"
        return self.u1

    def __str__(self):
        return "The mesh problem (M)"

def extract_num_dofs(F, S, M):
    "Extract the number of dofs"
    return F.num_dofs + S.num_dofs + M.num_dofs

def extract_solution(F, S, M):
    "Extract solution from sub problems"

    # Extract solutions from subproblems
    u_F, p_F = F.solution()
    U_S, P_S = S.solution()
    U_M = M.solution()

    # Pack up solutions
    U = (u_F, p_F, U_S, P_S, U_M)

    return U
