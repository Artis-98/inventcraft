"""Native icLogic slider forms; no application UI changes are needed."""

LEGS=('FL','FR','RL','RR')


def control_sets():
    sets={}
    for side in LEGS:
        sets['Leg controls '+side]=[
            ('slider','lift_'+side,-8,58,1,'Leg lift (degrees)'),
            ('slider','spread_'+side,30,62,1,'Leg spread (degrees)'),
            ('slider','steer_'+side,-14,14,1,'Wheel steering (degrees)'),
            ('slider','spin_'+side,-180,180,5,'Wheel rotation (degrees)'),
        ]
    sets['Boom and chassis controls']=[
        ('slider','boom_angle',10,65,1,'Boom lift (degrees)'),
        ('slider','dipper_angle',-120,-35,1,'Dipper (degrees)'),
        ('slider','bucket_curl',-30,100,1,'Bucket curl (degrees)'),
        ('slider','slew',-180,180,1,'Upper carriage slew (degrees)'),
        ('slider','chassis_pitch',-10,10,1,'Chassis nose-up pitch (degrees)'),
        ('slider','attachment_tilt',-35,35,1,'Attachment tilt (degrees)'),
        ('slider','attachment_rotation',-180,180,5,'Attachment rotation (degrees)'),
        ('slider','ride_height',900,2800,5,'Chassis height (mm)'),
        ('slider','wheel_spin',-180,180,5,'All wheels rotation (degrees)'),
    ]
    return sets


def install(assembly):
    engine=assembly.rules.rules[0].source
    for title,controls in control_sets().items():
        calls=["note('Live articulation. OK keeps the pose; Cancel restores it. Chassis height is independent of leg lift.')"]
        if title.startswith('Leg'):
            calls.append("note('The leg is a parallelogram: the wheel stays parallel to the chassis at every lift. A small cylinder steers each wheel about its kingpin.')")
        for _,param,low,high,step,label in controls:
            calls.append('slider('+','.join(map(repr,(param,low,high,step,label)))+')')
        source='form('+repr(title)+',\n    '+',\n    '.join(calls)+')\n'+engine
        rule=assembly.rules.add(title,source)
        rule.button=True
        rule.on_rebuild=False
        rule.watch=[]
