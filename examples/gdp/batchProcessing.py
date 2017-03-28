import pyomo.environ
from pyomo.core import *
from pyomo.gdp import *

'''Problem from http://www.minlp.org/library/problem/index.php?i=172&lib=GDP
We are minimizing the cost of a design of a plant with parallel processing units and storage tanks
in between. We decide the number and volume of units, and the volume and location of the storage
tanks. The problem is convexified and has a nonlinear objective and global constraints

NOTE: When I refer to 'gams' in the comments, that is Batch101006_BM.gms for now. It's confusing
because the _opt file is different (It has hard-coded bigM parameters so that each constraint 
has the "optimal" bigM).'''

model = AbstractModel()

# TODO: it looks like they set a bigM for each j. Which I need to look up how to do...
model.BigM = Suffix(direction=Suffix.LOCAL)
model.BigM[None] = 1000


## Constants from GAMS
StorageTankSizeFactor = 2*5 # btw, I know 2*5 is 10... I don't know why it's written this way in GAMS?
StorageTankSizeFactorByProd = 3
VolumeLB = log(300)
VolumeUB = log(3500)
StorageTankSizeLB = log(100)
StorageTankSizeUB = log(15000)
UnitsInParallelUB = log(6)
# TODO: YOU ARE HERE. YOU HAVEN'T ACTUALLY MADE THESE THE BOUNDS YET, NOR HAVE YOU FIGURED OUT WHOSE
# BOUNDS THEY ARE. AND THERE ARE MORE IN GAMS.


##########
# Sets
##########

model.PRODUCTS = Set(ordered=True)
model.STAGES = Set(ordered=True)

# TODO: this seems like an over-complicated way to accomplish this task...
def filter_out_last(model, j):
    return j != model.STAGES.last()
model.STAGESExceptLast = Set(initialize=model.STAGES, filter=filter_out_last)


# TODO: these aren't in the formulation??
#model.STORAGE_TANKS = Set()


###############
# Parameters
###############

model.HorizonTime = Param()
# alpha1
model.Alpha1 = Param()
model.Alpha2 = Param()
# TODO: this is about to be a mess. A bunch of these are hard-coded into the GAMS model...
model.Beta1 = Param()
model.Beta2 = Param()

model.ProductionAmount = Param(model.PRODUCTS)
model.ProductSizeFactor = Param(model.PRODUCTS, model.STAGES)
model.ProcessingTime = Param(model.PRODUCTS, model.STAGES)

# These are hard-coded in the GAMS file
model.StorageTankSizeFactor = Param(model.STAGES, default=StorageTankSizeFactor)
model.StorageTankSizeFactorByProd = Param(model.PRODUCTS, model.STAGES, 
                                          default=StorageTankSizeFactorByProd)

# TODO: bonmin wasn't happy and I think it might have something to do with this?
# or maybe issues with convexity... I don't know yet.
def get_log_coeffs(model, i):
    return log(model.PRODUCTS.ord(i))

model.LogCoeffs = Param(model.PRODUCTS, initialize=get_log_coeffs)

# bounds
model.volumeLB = Param(model.STAGES, default=VolumeLB)
model.volumeUB = Param(model.STAGES, default=VolumeUB)
model.storageTankSizeLB = Param(model.


################
# Variables
################

# TODO: right now these match the formulation. There are more in GAMS...

# unit size of stage j
model.volume = Var(model.STAGES)
# TODO: GAMS has a batch size indexed just by products that isn't in the formulation... I'm going
# to try to avoid it for the moment...
# batch size of product i at stage j
model.batchSize = Var(model.PRODUCTS, model.STAGES)
# TODO: this is different in GAMS... They index by stages too?
# cycle time of product i divided by batch size of product i
model.cycleTime = Var(model.PRODUCTS)
# number of units in parallel out-of-phase (or in phase) at stage j
model.unitsOutOfPhase = Var(model.STAGES)
model.unitsInPhase = Var(model.STAGES)
# TODO: what are we going to do as a boundary condition here? For that last stage?
# size of intermediate storage tank between stage j and j+1
model.storageTankSize = Var(model.STAGES)

# variables for convexified problem
model.volume_log = Var(model.STAGES)
model.batchSize_log = Var(model.PRODUCTS, model.STAGES)
model.cycleTime_log = Var(model.PRODUCTS)
model.unitsOutOfPhase_log = Var(model.STAGES)
model.unitsInPhase_log = Var(model.STAGES)
model.storageTankSize_log = Var(model.STAGES)

# binary variables for deciding number of parallel units in and out of phase
model.outOfPhase = Var(model.STAGES, model.PRODUCTS, within=Binary)
model.inPhase = Var(model.STAGES, model.PRODUCTS, within=Binary)

###############
# Objective
###############

def get_cost_rule(model):
    return model.Alpha1 * sum(exp(model.unitsInPhase_log[j] + model.unitsOutOfPhase_log[j] + \
                                          model.Beta1 * model.volume_log[j]) for j in model.STAGES) +\
        model.Alpha2 * sum(exp(model.Beta2 * model.storageTankSize_log[j]) for j in model.STAGESExceptLast)
model.min_cost = Objective(rule=get_cost_rule)


##############
# Constraints
##############

def processing_capacity_rule(model, j, i):
    return model.volume_log[j] >= log(model.ProductSizeFactor[i, j]) + model.batchSize_log[i, j] - \
        model.unitsInPhase_log[j]
model.processing_capacity = Constraint(model.STAGES, model.PRODUCTS, rule=processing_capacity_rule)

def processing_time_rule(model, j, i):
    return model.cycleTime_log[i] >= log(model.ProcessingTime[i, j]) - model.batchSize_log[i, j] - \
        model.unitsOutOfPhase_log[j]
model.processing_time = Constraint(model.STAGES, model.PRODUCTS, rule=processing_time_rule)

def finish_in_time_rule(model):
    return model.HorizonTime >= sum(model.ProductionAmount[i]*exp(model.cycleTime_log[i]) \
                                    for i in model.PRODUCTS)
model.finish_in_time = Constraint(rule=finish_in_time_rule)


###############
# Disjunctions
###############

def storage_tank_selection_disjunct_rule(disjunct, selectStorageTank, j):
    model = disjunct.model()
    def volume_stage_j_rule(disjunct, i):
        return model.storageTankSize_log[j] >= log(model.StorageTankSizeFactor[j]) + \
            model.batchSize_log[i, j]
    def volume_stage_jPlus1_rule(disjunct, i):
        return model.storageTankSize_log[j] >= log(model.StorageTankSizeFactor[j]) + \
            model.batchSize_log[i, j+1]
    def batch_size_rule(disjunct, i):
        return -log(model.StorageTankSizeFactorByProd[i,j]) <= model.batchSize_log[i,j] - \
            model.batchSize_log[i, j+1] <= log(model.StorageTankSizeFactorByProd[i,j])
    def no_batch_rule(disjunct, i):
        return model.batchSize_log[i,j] - model.batchSize_log[i,j+1] == 0

    if selectStorageTank:
        disjunct.volume_stage_j = Constraint(model.PRODUCTS, rule=volume_stage_j_rule)
        disjunct.volume_stage_jPlus1 = Constraint(model.PRODUCTS, 
                                                  rule=volume_stage_jPlus1_rule)
        disjunct.batch_size = Constraint(model.PRODUCTS, rule=batch_size_rule)
    else:
        # TODO: this is different in GAMS--they don't make it 0. I don't know why.
        # mine matches the formulation for now.
        disjunct.no_volume = Constraint(expr=model.storageTankSize_log[j] == 0)
        disjunct.no_batch = Constraint(model.PRODUCTS, rule=no_batch_rule)
model.storage_tank_selection_disjunct = Disjunct([0,1], model.STAGESExceptLast, 
                                       rule=storage_tank_selection_disjunct_rule)

def select_storage_tanks_rule(model, j):
    return [model.storage_tank_selection_disjunct[selectTank, j] for selectTank in [0,1]]
model.select_storage_tanks = Disjunction(model.STAGESExceptLast, rule=select_storage_tanks_rule)

# though this is a disjunction in the GAMs model, it is more efficiently formulated this way:
def units_out_of_phase_rule(model, j):
    return model.unitsOutOfPhase_log[j] == sum(model.LogCoeffs[i] * model.outOfPhase[j,i] \
                                               for i in model.PRODUCTS)
model.units_out_of_phase = Constraint(model.STAGES, rule=units_out_of_phase_rule)

def units_in_phase_rule(model, j):
    return model.unitsInPhase_log[j] == sum(model.LogCoeffs[i] * model.inPhase[j,i] \
                                            for i in model.PRODUCTS)
model.units_in_phase = Constraint(model.STAGES, rule=units_in_phase_rule)

# and since I didn't do the disjunction as a disjunction, we need to do the XORs:
def units_out_of_phase_xor_rule(model, j):
    return sum(model.outOfPhase[j,i] for i in model.PRODUCTS) == 1
model.units_out_of_phase_xor = Constraint(model.STAGES, rule=units_out_of_phase_xor_rule)

def units_in_phase_xor_rule(model, j):
    return sum(model.inPhase[j,i] for i in model.PRODUCTS) == 1
model.units_in_phase_xor = Constraint(model.STAGES, rule=units_in_phase_xor_rule)
