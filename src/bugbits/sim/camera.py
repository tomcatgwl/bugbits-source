"""Native STATIC camera branches on an explicitly engineering outer clock.

World transform and cached matrix generations remain separate. Normal running
gates/no shake/non-alias refresh are simulation qualifications, not original
OS-frame, complete effects or x87 bit-parity claims.
"""
from copy import deepcopy
import math
from bugbits.sim.nectar import f32

SCOPE = 'normal-camera-static-branches-outer20hz-v1'
IDENTITY = (1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.,0.,0.,0.,0.,1.)


class CameraClientInput:
    """Interface client state; world constructor state remains independent."""
    def __init__(self):
        self.position = (512, 384)
        self.size = (1024, 768)
        self.sequence = 0
        self.source = 'native-interface-constructor-v1'

    def sample(self, virtual_width):
        return (f32(virtual_width * self.position[0] / self.size[0]),
                f32(1200 * self.position[1] / self.size[1]))

    def update(self, position, size, sequence, source='signed-client-input-v1'):
        if (not isinstance(position, (list, tuple)) or len(position) != 2
                or any(type(v) is not int or not -32768 <= v <= 32767 for v in position)
                or not isinstance(size, (list, tuple)) or len(size) != 2
                or any(type(v) is not int or not 1 <= v <= 0x7fffffff for v in size)
                or type(sequence) is not int or not 1 <= sequence <= 9007199254740991
                or source not in ('signed-client-input-v1',
                                  'gameviewport-to-client1024x768-adapter-v1')):
            raise ValueError('signed client point, positive signed dimensions and input sequence required')
        if sequence <= self.sequence:
            return False
        self.position, self.size = tuple(position), tuple(size)
        self.sequence, self.source = sequence, source
        return True

    def snapshot(self):
        return dict(positionClient=list(self.position), sizeClient=list(self.size),
                    sequence=self.sequence, source=self.source)


def _mm(a,b):
    return [[f32(sum(a[i][k]*b[k][j] for k in range(3))) for j in range(3)] for i in range(3)]


def _rx(a):
    c,s = f32(math.cos(a)),f32(math.sin(a))
    return [[1.,0.,0.],[0.,c,-s],[0.,s,c]]


def _ry(a):
    c,s = f32(math.cos(a)),f32(math.sin(a))
    return [[c,0.,s],[0.,1.,0.],[-s,0.,c]]


def _inverse(m):
    a,b,c=m[0]; d,e,f=m[1]; g,h,i=m[2]
    det=a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)
    if not math.isfinite(det) or abs(det)<1e-12:raise ValueError('invertible camera required')
    return [[(e*i-f*h)/det,(c*h-b*i)/det,(b*f-c*e)/det],
            [(f*g-d*i)/det,(a*i-c*g)/det,(c*d-a*f)/det],
            [(d*h-e*g)/det,(b*g-a*h)/det,(a*e-b*d)/det]]


class NativeCamera:
    def __init__(self,props,*,virtual_width=1600,incoming_world=IDENTITY,client_input=None):
        self.config={k:f32(float(props[k][0])) for k in
            ('MinCamDistance','MaxCamDistance','MinAngle','MaxYaw','Width','Height')}
        self.offset_raw=tuple(f32(float(x)) for x in props['Offset'])
        if len(self.offset_raw)!=3 or not all(math.isfinite(x)
                for x in (*self.config.values(),*self.offset_raw)):
            raise ValueError('finite camera configuration required')
        if (self.config['MinCamDistance']<=0 or self.config['Width']<=0 or self.config['Height']<=0
                or type(virtual_width) is not int or virtual_width<=0):
            raise ValueError('positive camera dimensions required')
        self.virtual_width=virtual_width
        self.incoming_world=tuple(map(f32,incoming_world))
        if len(self.incoming_world)!=16 or not all(map(math.isfinite,self.incoming_world)):
            raise ValueError('finite raw world transform required')
        if self.incoming_world[3:12:4]!=(0.,0.,0.) or self.incoming_world[15]!=1.:
            raise ValueError('affine world transform required')
        rotation=[[self.incoming_world[4*i+j] for j in range(3)] for i in range(3)]
        for i in range(3):
            for j in range(3):
                if abs(sum(rotation[i][k]*rotation[j][k] for k in range(3))-float(i==j))>1e-6:
                    raise ValueError('camera supports rigid world parents only')
        a,b,c=rotation[0];d,e,f=rotation[1];g,h,i=rotation[2]
        if abs(a*(e*i-f*h)-b*(d*i-f*g)+c*(d*h-e*g)-1)>1e-6:
            raise ValueError('camera requires proper world rotation')
        self.recompose=False
        self.active=self.refresh_non_alias=True
        self.client_input = client_input if client_input is not None else CameraClientInput()
        self.sampled_input_sequence = None
        self.input_xy=(0.,0.)  # World ctor+278/+27C, not ceCamera's matrix fields.
        self.distance=f32(1920*self.config['MaxCamDistance']/virtual_width)
        self.goal_distance=self.distance
        if self.distance<=self.config['MinCamDistance']:raise ValueError('virtual max <= min')
        self.yaw=self.goal_yaw=self.pitch=0.
        self.target_raw=(0.,0.,-25.)
        self.tracked_id=None
        self.pre_driver_mode=self.camera_mode=self.generation=0
        self._untracked_drive(f32(.01))
        self.target_raw=self.offset_raw  # Actual post-driver target overwrite.
        self._local()
        self.e8_raw=self._propagated()
        self.e8_generation=0
        self.world_view=self._view()
        self.submitted_view=deepcopy(self.world_view)

    def _untracked_drive(self,h):
        minimum=self.config['MinCamDistance']
        maximum=1920*self.config['MaxCamDistance']/self.virtual_width
        ratio_y = f32(self.input_xy[1] / 1200)  # Original FSTP DWORD before coefficient multiply.
        self.goal_distance=f32(minimum+(maximum-minimum)*(.75+f32(.2)*ratio_y))
        self.distance=f32(self.distance+(self.goal_distance-self.distance)*h*1.5)
        ratio=f32((self.distance-minimum)/(maximum-minimum))
        factor=f32(1-ratio)
        lead=(f32((self.input_xy[0]-int(self.virtual_width/2))/self.virtual_width*self.config['Width']),
              f32((600-self.input_xy[1])/1200*self.config['Height']),0.)
        goal=tuple(f32(offset+f32(factor*x)) for offset,x in zip(self.offset_raw,lead))
        self.goal_yaw=(f32(-(self.input_xy[0]-int(self.virtual_width/2))/self.virtual_width
                          *(.75-ratio)*self.config['MaxYaw']) if ratio<.75 else 0.)
        self._smooth(h,goal,ratio)

    def focus(self,actor_id):
        self.tracked_id=actor_id

    def set_client_input(self, position, size, sequence, source='signed-client-input-v1'):
        return self.client_input.update(position, size, sequence, source)

    def advance(self,h,tracked=None):
        h=f32(h)
        if not math.isfinite(h) or h<0:raise ValueError('finite nonnegative camera seconds required')
        # Qualified normal world gate samples the interface before the driver,
        # including a zero-dt update. No sampling during constructor priming.
        self.input_xy = self.client_input.sample(self.virtual_width)
        self.sampled_input_sequence = self.client_input.sequence
        # Renderer samples the cached layer view BEFORE layer/world updates.
        self.submitted_view=deepcopy(self.world_view)
        if not self.active:return
        if self.recompose or not self.refresh_non_alias:
            raise ValueError('camera requires qualified non-recompose/non-alias branch')
        if h>f32(.2):h=0.
        self.pre_driver_mode=int(self.tracked_id is not None)
        if self.tracked_id is not None and (tracked is None or
                tracked['dialogueElapsed']>tracked['dialogueDuration']-3):
            self.tracked_id=None
        self.generation+=1
        if self.tracked_id is None:
            self._untracked_drive(h)
        else:
            if tracked['id']!=self.tracked_id:raise ValueError('camera focus identity mismatch')
            a,b,c=map(f32,tracked['positionRaw'])
            minimum=self.config['MinCamDistance']
            maximum=1920*self.config['MaxCamDistance']/self.virtual_width
            self.goal_distance=minimum
            self.distance=f32(self.distance+(minimum-self.distance)*h*1.5)
            self.distance=f32(self.distance+(minimum-c-self.distance)*h*2)
            ratio=f32((self.distance-minimum)/(maximum-minimum))
            # Native clamp uses Offset.A +/- Width/2; yaw keeps original A.
            limit=self.config['Width']/2
            clipped=max(self.offset_raw[0]-limit,min(self.offset_raw[0]+limit,a))
            factor=f32(1-ratio)
            goal=(f32(factor*clipped),f32(factor*b),0.)
            self.goal_yaw=f32(-a/self.config['Width']*(.75-ratio)*self.config['MaxYaw']) if ratio<.75 else 0.
            self._smooth(h,goal,ratio)
        self._local()

    def finish_frame(self):
        if not self.active:return
        # World view reads cached E8 plus current physics eye before slot11.
        self.world_view=self._view()
        self.e8_raw=self._propagated()
        self.e8_generation=self.generation
        # Normal cGame Update calls world10/11 before device Draw. The view
        # was refreshed before world11, so submission still uses cached E8.
        self.submitted_view=deepcopy(self.world_view)

    def _smooth(self,h,goal,ratio):
        self.yaw=f32(self.yaw+(self.goal_yaw-self.yaw)*h*1.5)
        self.target_raw=tuple(f32(old+f32(f32(f32(want-old)*h)*1.5))
                              for old,want in zip(self.target_raw,goal))
        self.pitch=f32(self.config['MinAngle']-self.config['MinAngle']*ratio)
        self.camera_mode=3

    def _local(self):
        theta=1.5707963705062866
        n=_mm(_mm(_rx(f32(self.pitch-theta)),_ry(self.yaw)),_rx(theta))
        inv=_inverse(n)
        self.eye_raw=tuple(f32(x-inv[i][2]*self.distance) for i,x in enumerate(self.target_raw))
        self.local_raw=tuple(n[j][i] if i<3 and j<3 else self.eye_raw[j]
            if i==3 and j<3 else float(i==j) for i in range(4) for j in range(4))

    def _propagated(self):
        a,b=self.local_raw,self.incoming_world
        return tuple(f32(sum(a[4*i+k]*b[4*k+j] for k in range(4)))
                     for i in range(4) for j in range(4))

    def _view(self):
        e=self.e8_raw
        basis=[v for j in range(3) for v in (-e[4+j],-e[8+j],e[j])]
        a,b,c=self.eye_raw
        return dict(basis9=basis,cameraPosition=[-b,-c,a],
                    basisGeneration=self.e8_generation,eyeGeneration=self.generation)

    def snapshot(self):
        return deepcopy(dict(scope=SCOPE,config=self.config,offsetRaw=list(self.offset_raw),
            virtualWidth=self.virtual_width,distance=self.distance,goalDistance=self.goal_distance,
            yaw=self.yaw,goalYaw=self.goal_yaw,pitch=self.pitch,targetRaw=list(self.target_raw),
            trackedId=self.tracked_id,preDriverMode=self.pre_driver_mode,cameraMode=self.camera_mode,
            generation=self.generation,incomingWorldRaw=list(self.incoming_world),
            cameraA8Raw=list(self.local_raw),cameraE8Raw=list(self.e8_raw),e8Generation=self.e8_generation,
            worldView=self.world_view,view=self.submitted_view,inputXY=list(self.input_xy),
            clientInput=self.client_input.snapshot(),sampledInputSequence=self.sampled_input_sequence,
            recompose=self.recompose,active=self.active,refreshNonAlias=self.refresh_non_alias,
            qualification='engineering-enabled-gates-no-shake-no-overlap-world-input-v1'))
