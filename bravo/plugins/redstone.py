from itertools import chain, product

from twisted.internet.defer import inlineCallbacks, maybeDeferred, returnValue
from twisted.internet.task import LoopingCall
from zope.interface import implements

from bravo.blocks import blocks, items
from bravo.ibravo import IAutomaton, IDigHook
from bravo.utilities.automatic import naive_scan

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

class RedstoneCircuit(object):

    implements(IAutomaton, IDigHook)

    step = 0.2

    blocks = (blocks["stone-button"].slot, blocks["redstone-torch"].slot, blocks["redstone-torch-off"].slot)

    def __init__(self):
        self.tracked = set()
        self.trackedTorches = set()
        
        self.opennodes = set()
        self.closednodes = set()

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

    @inlineCallbacks
    def update_redstone_ciruit(self):
        world = factory.world
        
        self.opennodes = set()
        self.closednodes = set()
        
        def isTorchBase(coords):
            return any(basecoords == coords for basecoords, torchcoords, orientation in self.trackedTorches)
        
        @inlineCallbacks
        def isTorch(coords):
            """
                TODO: optimize speed with caching?
            """
            block = yield world.get_block(coords)
            returnValue((block in (blocks["redstone-torch"].slot, blocks["redstone-torch-off"].slot)))
        
        @inlineCallbacks
        def isRedstoneWire(coords):
            """
                TODO: optimize speed with caching?
            """
            block = yield world.get_block(coords)
            returnValue((block == blocks["redstone-wire"].slot))
        
        def getTorchFromBase(coords):
            for basecoords, torchcoords, orientation in self.trackedTorches:
                if basecoords == coords:
                    return (torchcoords, orientation)
            return None
        
        def hasPrevious(coords):
            for blockcoords, previous in self.closednodes:
                if blockcoords == coords:
                    return not previous is None
            
            for blockcoords, previous in self.opennodes:
                if blockcoords == coords:
                    return not previous is None
            
            return False
        
        @inlineCallbacks
        def expandTorch(torch, previous=None, on=True):
            """
                expand redstone torch
            """
            
            basecoords, torchcoords, orientation = torch
            x, y, z = torchcoords
            
            print "expanding torch"
            
            #switch power
            block = yield world.get_block(torchcoords)
            if on and block == blocks["redstone-torch-off"].slot:
                meta = yield world.get_metadata(torchcoords)
                block = yield world.set_block(torchcoords, blocks["redstone-torch"].slot)
                world.set_metadata(torchcoords, meta)
                print "torch is now on"
                
            elif not on and block == blocks["redstone-torch"].slot:
                meta = yield world.get_metadata(torchcoords)
                block = yield world.set_block(torchcoords, blocks["redstone-torch-off"].slot)
                world.set_metadata(torchcoords, meta)
                print "torch is now off"
            
            self.closednodes.add( (torchcoords, previous) )
            expanded = set()
            
            if orientation == TORCH_FACING_SOUTH:
                expanded.add( ((x+1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1), torchcoords) )
                if isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if isTorchBase((x, y+1, z)):
                    torchcoords, orientation = getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_NORTH:
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1, torchcoords)) )
                if isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_WEST:
                expanded.add( ((x, y, z+1), torchcoords) )
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                if isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_EAST:
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                if isRedstoneWire( (x, y-1, z) ):
                    expanded.add( ((x, y-1, z), torchcoords) )
                if isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
                
            elif orientation == TORCH_FACING_UP:
                expanded.add( ((x-1, y, z), torchcoords) )
                expanded.add( ((x+1, y, z), torchcoords) )
                expanded.add( ((x, y, z-1), torchcoords) )
                expanded.add( ((x, y, z+1), torchcoords) )
                if isTorchBase( (x, y+1, z) ):
                    torchcoords, orientation = getTorchFromBase( (x, y+1, z) )
                    expandTorch( ((x, y+1, z), torchcoords, orientation), previous=torchcoords, on=not on)
            
            expanded.difference_update(self.closednodes)
            self.opennodes.update(expanded)
                
        for torch in self.trackedTorches:
            if not hasPrevious(torch[1]):
                expandTorch(torch, on=True)
        
        while True:
            try:
                coords, previous = self.opennodes.pop()
            except KeyError:
                break
            print "processing node"
            
            if isTorchBase(coords):
                print "got torch base"
                pass
            elif (yield isRedstoneWire(coords)):
                print "got wire"
                if (yield isRedstoneWire(previous)):
                    print "previous was wire"
                    level = yield world.get_metadata(previous)
                    if level > 0:
                        level -= 1
                    print "new level", level
                    world.set_metadata(coords, level)
                elif (yield isTorch(previous)):
                    print "previous was torch"
                    block = yield world.get_block(previous)
                    if block == blocks["redstone-torch"].slot: #torch on
                        level = 0xf
                    else: #torch off
                        level = 0
                    print "new level", level
                    world.set_metadata(coords, level)
                
                x, y, z = coords
                
                neighbors = [(x+1, y, z), (x-1, y, z), (x, y, z+1), (x, y, z-1)]
                neighbors.remove(previous)
                for new in neighbors:
                    self.opennodes.add( (new, coords) )
            
            self.closednodes.add( (coords, previous) )

    @inlineCallbacks
    def process(self):
        world = factory.world
        self.trackedTorches = set()
        
        destroyed = set()
        
        for x, y, z in self.tracked:
            block = yield world.get_block((x, y, z))
            
            if block in (blocks["redstone-torch-off"].slot, blocks["redstone-torch"].slot):
                meta = yield factory.world.get_metadata((x, y, z))
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
                
            else:
                destroyed.add( (x, y, z) )
        
        map(self.trackedTorches.discard, destroyed)
        
        self.update_redstone_ciruit()
    
    def feed(self, coords):
        self.tracked.add(coords)

    scan = naive_scan

    def dig_hook(self, chunk, x, y, z, block):
        pass

    name = "redstone-circuit"

    before = ("build",)
    after = tuple()

redstoneCircuit = RedstoneCircuit()
