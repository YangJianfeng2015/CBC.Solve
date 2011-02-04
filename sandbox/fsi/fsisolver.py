__author__ = "Kristoffer Selim and Anders Logg"
__copyright__ = "Copyright (C) 2010 Simula Research Laboratory and %s" % __author__
__license__  = "GNU GPL Version 3 or any later version"

# Last changed: 2011-02-05

__all__ = ["FSISolver"]

from time import time

from dolfin import *
from cbc.common import CBCSolver

from primalsolver import solve_primal
from dualsolver import solve_dual
from adaptivity import estimate_error, refine_mesh, save_mesh

class FSISolver(CBCSolver):

    def __init__(self, problem):
        "Initialize FSI solver"

        # Initialize base class
        CBCSolver.__init__(self)

        # Set DOLFIN parameters
        parameters["form_compiler"]["cpp_optimize"] = True

        # Store problem
        self.problem = problem

    def solve(self, parameters):
        "Solve the FSI problem (main adaptive loop)"

        # Get parameters
        tolerance = parameters["tolerance"]
        w_h = parameters["w_h"]

        # Create empty solution (return value when primal is not solved)
        U = 5*(None,)

        # Initial guess for stability factor
        ST = 1.0

        # Adaptive loop
        cpu_time = time()
        goal_functional = None
        while True:

            # Solve primal problem
            if parameters["solve_primal"]:
                begin("Solving primal problem")
                goal_functional = solve_primal(self.problem, parameters, ST)
                end()
            else:
                info("Not solving primal problem")

            # Solve dual problem
            if parameters["solve_dual"]:
                begin("Solving dual problem")
                solve_dual(self.problem, parameters)
                end()
            else:
                info("Not solving dual problem")

            # Estimate error and compute error indicators
            if parameters["estimate_error"]:
                begin("Estimating error and computing error indicators")
                error, indicators, ST, E_h = estimate_error(self.problem, parameters)
                end()
            else:
                info("Not estimating error")
                error = 0.0

            # Check if error is small enough
            begin("Checking error estimate")
            if error <= tolerance:
                info_green("Adaptive solver converged: error = %g <= TOL = %g" % (error, tolerance))
                break
            else:
                info_red("Error too large, need to refine: error = %g > TOL = %g" % (error, tolerance))
            end()

            # Check if mesh error is small enough
            begin("Checking space error estimate")
            mesh_tolerance = w_h * tolerance
            if E_h <= mesh_tolerance:
                info_blue("Freezing current mesh: E_h = %g <= TOL_h = %g" % (E_h, mesh_tolerance))
                refined_mesh = self.problem.mesh()
            else:
                info_red("Refining mesh")

                # Check: If convergence_test = True and etimate_error = True, the mesh
                # will adapt but the time step is set according to the convergence test
                if self.problem.convergence_test() and not self.problem.estimate_error():
                    refined_mesh = refine(self.problem.mesh())

                # Refine according to error estimate
                else:
                    refined_mesh = refine_mesh(self.problem, self.problem.mesh(), indicators)

                self.problem.init_meshes(refined_mesh)
            end()

            # Update and save mesh
            mesh = refined_mesh
            save_mesh(mesh)

        # Report elapsed time
        info_blue("Solution computed in %g seconds." % (time() - cpu_time))

        # Return solution
        return goal_functional
