"""Public pose-to-textured-render contract, with hand-picked texel literals."""
import sys
import copy
from pathlib import Path
import unittest
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from bugbits.assets import pose
from bugbits.render import software

IDENTITY=(1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1)


def geometry():
    points=((-3,-1,0),(-1,-1,0),(-2,1,0),(1,-1,0),(3,-1,0),(2,1,0))
    verts=[(p,(0,0,-1),(.25,.75) if i<3 else (.75,.75)) for i,p in enumerate(points)]
    skin=[(p,n,[(0,1.)]) for p,n,_ in verts]
    return verts,skin


def render(vertices):
    tex=Image.new('RGB',(2,2))
    tex.putdata([(200,0,0),(0,200,0),(0,0,200),(200,200,0)])
    return software.render(vertices,[0,1,2,3,4,5],tex,size=32,yaw=0,pitch=0,
                           norm_span=8,center=(0,0,0))[0]


class PoseUVTests(unittest.TestCase):
    def test_animated_vertices_render_two_original_texels_without_changing_pose(self):
        verts,skin=geometry()
        anim=IDENTITY[:14]+(1,1)
        old=pose.skin_at(skin,[IDENTITY],[anim])
        old_image=render(old)
        self.assertEqual(old_image.getpixel((10,16)),(40,40,90,255))
        self.assertEqual(old_image.getpixel((22,16)),(40,40,90,255))
        actual=pose.skin_at(skin,[IDENTITY],[anim],source_vertices=verts)
        image=render(actual)
        self.assertEqual(image.getpixel((10,16)),(90,40,40,255))
        self.assertEqual(image.getpixel((22,16)),(40,90,40,255))
        self.assertEqual([v[:2] for v in actual],[v[:2] for v in old])
        self.assertEqual(actual[0][0],(-3.,-1.,1.))

    def test_explicit_source_mapping_rejects_wrong_order_count_or_nonfinite_uv(self):
        verts,skin=geometry()
        candidates=[verts[:-1],verts+[verts[0]],list(reversed(verts)),None,True]
        for position in ((0,0),(-3,-1,0,2),(float('nan'),-1,0),(True,-1,0),('x',-1,0)):
            bad=copy.deepcopy(verts);bad[0]=(position,bad[0][1],bad[0][2]);candidates.append(bad)
        for uv in ((.2,),(.2,.3,.4),(float('inf'),.3),(float('nan'),.3),(True,.3),('0',.3),None):
            bad=copy.deepcopy(verts);bad[0]=(bad[0][0],bad[0][1],uv);candidates.append(bad)
        for source in candidates:
            if source is None:continue  # None is the explicit legacy compatibility mode.
            with self.subTest(source=source),self.assertRaises(ValueError):
                pose.skin_at(skin,[IDENTITY],[IDENTITY],source_vertices=source)

    def test_three_argument_compatibility_keeps_position_normal_and_zero_uv(self):
        _,skin=geometry()
        actual=pose.skin_at(skin,[IDENTITY],[IDENTITY])
        self.assertEqual(actual[0],((-3.,-1.,0.),(0.,0.,-1.),(0.,0.)))


if __name__=='__main__':unittest.main()
