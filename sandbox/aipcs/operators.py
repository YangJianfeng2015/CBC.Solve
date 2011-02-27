"This module defines special operators for the dual problem and residuals."

__author__ = "Kristoffer Selim and Anders Logg"
__copyright__ = "Copyright (C) 2010 Simula Research Laboratory and %s" % __author__
__license__  = "GNU GPL Version 3 or any later version"

# Last changed: 2011-02-27

from dolfin import *
from cbc.twist import DeformationGradient as F
from cbc.twist import Jacobian as J
from cbc.twist import GreenLagrangeStrain as E

# Define identity matrix (2D)
I = Identity(2)

def Sigma_F(U_F, P_F, mu_F):
    "Return fluid stress in reference domain (not yet Piola mapped)"
    return mu_F*(grad(U_F) + grad(U_F).T) - P_F*I

def Sigma_S(U_S, mu_S, lmbda_S):
    "Return structure stress in reference domain"
    return dot(F(U_S), 2*mu_S*E(U_S) + lmbda_S*tr(E(U_S))*I)
