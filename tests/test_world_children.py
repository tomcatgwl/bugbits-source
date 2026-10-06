"""Independent unsigned-name, live traversal and original remove-loop examples."""
import unittest
from bugbits.sim.world_children import NamedChildren


class NamedChildrenTests(unittest.TestCase):
    def test_unsigned_case_sensitive_order_suffix_width_and_name_reuse(self):
        scene=NamedChildren()
        for key,name in enumerate(('z','A','a','\xff','nectar09','nectar09','nectar09')):
            scene.add('fixture',key,name)
        self.assertEqual([e.name for e in scene.entries()],['A','a','nectar09','nectar10','nectar11','z','\xff'])
        scene.remove('fixture',4)
        self.assertEqual(scene.add('fixture',7,'nectar09'),'nectar09')
        self.assertEqual(scene.add('fixture',8,'009'),'009')
        self.assertEqual(scene.add('fixture',9,'009'),'010')
        for name in ('', 'a\0b', '\u4e2d', 'x'*241):
            with self.subTest(name=name),self.assertRaises(ValueError):scene.add('fixture',10,name)
        scene.add('fixture',11,'overflow2147483647')
        with self.assertRaises(ValueError):scene.add('fixture',12,'overflow2147483647')
        self.assertEqual(len(scene.entries()),10)

    def test_after_current_insertion_updates_now_and_before_current_revisits_current(self):
        for first,inserted,last,expected in (
                ('A','B','Z',['A','B','Z']),
                ('M','A','Z',['M','M','Z'])):
            with self.subTest(first=first):
                scene=NamedChildren();scene.add('fixture',1,first);scene.add('fixture',2,last)
                visited=[]
                def update(child):
                    visited.append(child.name)
                    if len(visited)==1:scene.add('fixture',3,inserted)
                scene.walk(update)
                self.assertEqual(visited,expected)

    def test_suffix_zero_padding_and_overflow_rejection_preserve_container(self):
        scene=NamedChildren()
        scene.add('fixture',1,'nectar0009')
        self.assertEqual(scene.add('fixture',2,'nectar0009'),'nectar0010')
        scene.add('fixture',3,'nectar2147483646')
        self.assertEqual(scene.add('fixture',4,'nectar2147483646'),'nectar2147483647')
        before=scene.entries()
        with self.assertRaises(ValueError):scene.add('fixture',5,'nectar2147483646')
        self.assertEqual(scene.entries(),before)
        boundary='x'*239+'9'
        scene.add('fixture',6,boundary)
        before=scene.entries()
        with self.assertRaises(ValueError):scene.add('fixture',7,boundary)
        self.assertEqual(scene.entries(),before)

    def test_static_slot_changes_sweep_shift_skip_position(self):
        scene=NamedChildren()
        scene.add('nectar',1,'nectar')
        scene.add('static',2,'nectar1')
        scene.add('nectar',3,'nectar2')
        removed=[]
        scene.sweep(lambda child:child.kind=='nectar',lambda child:removed.append(child.key))
        self.assertEqual(removed,[1,3])
        self.assertEqual([(child.kind,child.key) for child in scene.entries()],[('static',2)])

    def test_sweep_removes_before_callback_and_advances_over_shifted_neighbor(self):
        scene=NamedChildren()
        for i in range(3):scene.add('fixture',i,'nectar')
        removed=[]
        def destroy(child):
            self.assertNotIn(child,scene.entries())
            removed.append(child.key)
        scene.sweep(lambda child:True,destroy)
        self.assertEqual(removed,[0,2])
        self.assertEqual([child.key for child in scene.entries()],[1])
        scene.sweep(lambda child:True,destroy)
        self.assertEqual(removed,[0,2,1])


if __name__=='__main__':unittest.main()
