from itertools import chain, product

from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from twisted.internet.task import LoopingCall
from zope.interface import implements

from bravo.blocks import blocks, items
from bravo.ibravo import IAutomaton
from bravo.utilities.automatic import naive_scan
from bravo.utilities.coords import split_coords

from bravo.parameters import factory

BUTTON_FACING_WEST = 0x1
BUTTON_FACING_EAST = 0x2
BUTTON_FACING_SOUTH = 0x3
BUTTON_FACING_NORTH = 0x4

TORCH_FACING_SOUTH = 0x1
TORCH_FACING_NORTH = 0x2
TORCH_FACING_WEST = 0x3
TORCH_FACING_EAST = 0x4
TORCH_FACING_UP = 0x5

CIRCUIT_BLOCKS = [
    "redstone-wire",
    "redstone-torch",
    "redstone-torch-off",
    "redstone-repeater-on",
    "redstone-repeater-off",

    "stone-button",
    "stone-plate",
    "wooden-plate",
    "lever",

    "iron-door",
    "wooden-door",
]

class RedstoneCircuit(object):

    implements(IAutomaton)

    step = 0.2

    blocks = [blocks[name].slot for name in CIRCUIT_BLOCKS]

    def __init__(self):
        self.tracked = set()
        self.trackedTorches = set()
        self.trackedWires = set()
        
        self.opennodes = set()
        self.closednodes = set()
        
        self.touchedChunks = set()

        self.loop = LoopingCall(self.process)

    def start(self):
        if not self.loop.running:
            self.loop.start(self.step)

    def stop(self):
        if self.loop.running:
            self.loop.stop()

    def schedule(self):
        if self.tracked:
            self.start()
        else:
            self.stop()
    
    # track block changes
    
    @inlineCallbacks
    def getBlock(self, coords):
        returnValue((yield factory.world.get_block(coords)))
    
    def setBlock(self, coords, block):
        factory.world.set_block(coords, block)
        
        bigx, smallx, bigz, smallz = split_coords(coords[0], coords[2])
        self.touchedChunks.add( (bigx, smallz) )
    
    @inlineCallbacks
    def getMetadata(self, coords):
        returnValue((yield factory.world.get_metadata(coords)))
    
    def setMetadata(self, coords, meta):
        factory.world.set_metadata(coords, meta)
        
        bigx, smallx, bigz, smallz = split_coords(coords[0], coords[2])
        self.touchedChunks.add( (bigx, bigz) )
    
    @inlineCallbacks
    def flushChunks(self):
        for bigx, bigz in self.touchedChunks:
            chunk = yield factory.world.request_chunk(bigx, bigz)
            factory.flush_chunk(chunk)
    
    # helper functions
    
    def isTorchBase(self, coords):
        """
            is this block is a base for a redstone torch?
        """
        return any(basecoords == coords for basecoords, torchcoords, orientation in self.trackedTorches)
        
    @inlineCallbacks
    def isTorch(self, coords):
        """
            is this block a redstone torch?
        """
        block = yield self.getBlock(coords)
        returnValue((block in (blocks["redstone-torch"].slot, blocks["redstone-torch-off"].slot)))
    
    @inlineCallbacks
    def isRedstoneWire(self, coords):
        """
            is this block a redstone wire?
        """
        block = yield self.getBlock(coords)
        returnValue((block == blocks["redstone-wire"].slot))
    
    def getTorchFromBase(self, coords):
        """
            returns the torch and it's direction from it's base coords
        """
        for basecoords, torchcoords, orientation in self.trackedTorches:
            if basecoords == coords:
                return (torchcoords, orientation)
        return None
    
    def hasPrevious(self, coords):
        """
            visited node already?
        """
        for blockcoords, previous in self.closednodes:
            if blockcoords == coords:
                return not previous is None
        
        for blockcoords, previous in self.opennodes:
            if blockcoords == coords:
                return not previous is None
        
        return False
    
    
    
    @inlineCallbacks
    def updateRedstoneCiruits(self):
        """
            the real processing is happening here
        """
        world = factory.world
        
        #resetting lists
        self.opennodes = set()
        self.closednodes = set()
        
        @inlineCallbacks
        def expandTorch(torch, previous=None, on=True):
            """
                expand redstone torch
            """
            
            basecoords, torchcoords, orientation = torch
            x, y, z = torchcoords
            
            print "expanding torch"
            
            #indicates if the torch power was switched
            switched = False
            
            #switch power, if necessary
            block = yield self.getBlock(torchcoords)
            if on and block == blocks["redstone-torch-off"].slot:
                meta = yield self.getMetadata(torchcoords)
                block = yield self.setBlock(torchcoords, blocks["redstone-torch"].slot)
                self.setMetadata(torchcoords, meta)
                print "torch is now on"
                switched = True
                
            elif not on and block == blocks["redstone-torch"].slot:
                meta = yield self.getMetadata(torchcoords)
                block = yield self.setBlock(torchcoords, blocks["redstone-torch-off"].slot)
                self.setMetadata(torchcoords, meta)
                print "torch is now off"
                switched = True
            
            #move torch from open to closed list
            self.opennodes.discard( (torchcoords, previous) )
            self.closednodes.add( (torchcoords, previous) )
            expanded = set()
            
            #find decendants
            if orientation == TORCH_FACING_SOUTH:
                expanded.add( ((x+1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1), torchcoords) )
                if self.isRedstoneWire( (x, y-1, z) ): # block below is only powered if it's a wire (no repeater, etc.)
                    expanded.add( ((x, y-1, z), torchcoords) )
                if self.isTorchBase((x, y+1, z)): # check for torch elevator
                    torchcoords, orientation = self.getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_NORTH:
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1, torchcoords)) )
                if self.isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if self.isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = self.getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_WEST:
                expanded.add( ((x, y, z+1), torchcoords) )
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                if self.isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if self.isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = self.getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_EAST:
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                if self.isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if self.isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = self.getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_UP:
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1), torchcoords) )
                if self.isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = self.getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
            
            #if the torch was switched, we need to reprocess the descendants
            if not switched:
                expanded.difference_update(self.closednodes)
            self.opennodes.update(expanded)
        
        for torch in self.trackedTorches:
            #pick a unused starting torch for a circuit
            if not self.hasPrevious(torch[1]):
                print "----new circuit"

                block = yield self.getBlock(torch[1])
                if block == blocks["redstone-torch"].slot:
                    expandTorch(torch, on=True)
                #deactivated torches are processed at the end
            
            while True:
                try:
                    coords, previous = self.opennodes.pop()
                except KeyError:
                    break
                print "processing node"
                
                if self.isTorchBase(coords): #are we at a torch base?
                    print "got torch base"
                    if (yield self.isRedstoneWire(previous)): #was there a wire before?
                        print "previous was wire"
                        level = yield self.getMetadata(previous)
                        if level > 0: #wire is powered, turning torch off
                            print "wire is powered, turning off"
                            
                            torchcoords, orientation = self.getTorchFromBase(coords)
                            expandTorch((coords, torchcoords, orientation), previous=coords, on=False)
                        else: #wire is not powered, turning torch on
                            print "wire is not powered, turning on"
                            
                            torchcoords, orientation = self.getTorchFromBase(coords)
                            expandTorch((coords, torchcoords, orientation), previous=coords, on=True)
                elif (yield self.isRedstoneWire(coords)): #are we at a wire?
                    print "got wire"
                    if not previous: #lonely wire, ignore here (processed at the end)
                        continue
                    elif (yield self.isRedstoneWire(previous)): #previous was a wire
                        print "previous was wire"
                        level = yield self.getMetadata(previous)
                        if level > 0:
                            level -= 1 #reduce level
                        print "new level", level
                        self.setMetadata(coords, level)
                    elif (yield self.isTorch(previous)): #previous was torch, full power (or not)
                        print "previous was torch"
                        block = yield self.getBlock(previous)
                        if block == blocks["redstone-torch"].slot: #torch on
                            level = 0xf
                        else: #torch off
                            level = 0
                        print "new level", level
                        self.setMetadata(coords, level)
                        
                    x, y, z = coords
                    
                    #add neighbors to open list
                    #but exclude current block to prevent loop
                    neighbors = [(x+1, y, z), (x-1, y, z), (x, y, z+1), (x, y, z-1)]
                    neighbors.remove(previous)
                    for new in neighbors:
                        self.opennodes.add( (new, coords) )
                
                #block done
                self.closednodes.add( (coords, previous) )
        
        #resetting lonely wires
        for wire in self.trackedWires:
            if not self.hasPrevious(wire):
                print "resetting unused wire"
                self.setMetadata(wire, 0)
        
        #resetting lonely torches
        for torch in self.trackedTorches:
            if not self.hasPrevious(torch[0]):
                block = yield self.getBlock(torch[1])
                if block == blocks["redstone-torch-off"].slot:
                    print "resetting unpowered torch"
                    self.setBlock(torch[1], blocks["redstone-torch"].slot)
    
    @inlineCallbacks
    def process(self):
        """
            1. prepare circuit
             - check for torches
             - check for switches
             - check for removed blocks
            2. start updating
            3. flush changes
        """
        world = factory.world
        self.trackedTorches = set()
        self.trackedWires = set()
        
        destroyed = set()
        
        for x, y, z in self.tracked.copy(): #work with copy!
            block = yield self.getBlock((x, y, z))
            
            #preprocess blocks
            if block in (blocks["redstone-torch-off"].slot, blocks["redstone-torch"].slot): #preprocess power sources
                meta = yield self.getMetadata((x, y, z))
                if meta & (meta | TORCH_FACING_SOUTH) == TORCH_FACING_SOUTH:
                    self.trackedTorches.add( ((x-1, y, z), (x, y, z), TORCH_FACING_SOUTH) )
                    
                elif meta & (meta | TORCH_FACING_NORTH) == TORCH_FACING_NORTH:
                    self.trackedTorches.add( ((x+1, y, z), (x, y, z), TORCH_FACING_NORTH) )
                    
                elif meta & (meta | TORCH_FACING_WEST) == TORCH_FACING_WEST:
                    self.trackedTorches.add( ((x, y, z-1), (x, y, z), TORCH_FACING_WEST) )
                    
                elif meta & (meta | TORCH_FACING_EAST) == TORCH_FACING_EAST:
                    self.trackedTorches.add( ((x, y, z+1), (x, y, z), TORCH_FACING_EAST) )
                    
                elif meta & (meta | TORCH_FACING_UP) == TORCH_FACING_UP:
                    self.trackedTorches.add( ((x, y-1, z), (x, y, z), TORCH_FACING_UP) )
            elif block == blocks["redstone-wire"].slot: #preprocess wires
                self.trackedWires.add( (x, y, z) )
            else: #not a redstone related block anymore, mark for stop tracking
                destroyed.add( (x, y, z) )
        
        #stop tracking marked blocks
        map(self.trackedTorches.discard, destroyed)
        map(self.trackedWires.discard, destroyed)
        
        #do the updating
        self.updateRedstoneCiruits()
        #flush circuit state to clients
        self.flushChunks()
    
    def feed(self, coords):
        self.tracked.add(coords)

    scan = naive_scan

    name = "redstone-circuit"

    before = ("build",)
    after = tuple()

redstoneCircuit = RedstoneCircuit()
