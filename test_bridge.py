import json
from pathlib import Path
import unittest
from z1_bridge import decode_packet, KeyboardState, WindowsInput

HERE = Path(__file__).parent
def captured(name):
    return [bytes.fromhex(r['hex']) for line in (HERE/name).read_text().splitlines()
            if (r:=json.loads(line)).get('kind')=='packet']

class BridgeTests(unittest.TestCase):
    def test_captured_qwer_packets(self):
        frames = captured('key-samples.jsonl')
        self.assertEqual(len(frames),26)
        states = [decode_packet(p) for p in frames]
        self.assertTrue(all(s is not None for s in states))
        self.assertEqual(states[2:10],[{0x14},set(),{0x1A},set(),{8},set(),{0x15},set()])

    def test_real_modifiers_and_chord(self):
        states = [decode_packet(p) for p in captured('modifier-samples.jsonl')]
        self.assertEqual(states,[{0xE1},{0xE1,0x14},{0xE1},set(),
            {0x14},{0x14,0x1A},{0x1A},set(),{0xE0},set(),{0xE2},set(),{0x2C},set()])

    def test_invalid_frames_do_not_generate_input(self):
        original = captured('key-samples.jsonl')[2]
        for packet in [b'',original[:-1],original+b'\x00',original[:-1]+b'\x00']:
            self.assertIsNone(decode_packet(packet))
        error = bytearray(original)
        error[10]=1
        error[-1]=sum(error[:-1])&255
        self.assertIsNone(decode_packet(error))

    def test_press_release_order_and_pause_cleanup(self):
        events=[]
        state=KeyboardState(lambda key,down:events.append((key,down)))
        state.update({0x14,0xE1},now=0)
        state.release_all()
        self.assertEqual(events,[(0xE1,True),(0x14,True),(0x14,False),(0xE1,False)])
        self.assertFalse(state.down)
        state.release_all()
        self.assertEqual(len(events),4)

    def test_hold_repeat_and_release(self):
        events=[]
        state=KeyboardState(lambda k,d:events.append((k,d)),delay=.5,interval=.04)
        state.update({0x14},now=0)
        state.repeat(.49)
        self.assertEqual(len(events),1)
        state.repeat(.5)
        self.assertEqual(events,[(0x14,True),(0x14,True)])
        state.update(set(),now=.51)
        state.repeat(1)
        self.assertEqual(events[-1],(0x14,False))
        self.assertEqual(len(events),3)

    def test_real_replay_finishes_with_no_stuck_keys(self):
        for name in ['key-samples.jsonl','modifier-samples.jsonl']:
            events=[]
            state=KeyboardState(lambda k,d:events.append((k,d)))
            for packet in captured(name):
                state.update(decode_packet(packet))
            self.assertFalse(state.down)
            self.assertEqual(sum(1 if d else -1 for k,d in events),0)

    def test_windows_input_abi_without_injecting(self):
        sink=WindowsInput()
        self.assertGreater(sink.repeat_settings()[0],0)
        self.assertGreater(sink.repeat_settings()[1],0)

if __name__=='__main__':
    unittest.main(verbosity=2)
