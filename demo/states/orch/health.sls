# Demo orchestration: is everyone there, and on what Salt version?
everyone-answers:
  salt.function:
    - name: test.ping
    - tgt: '*'

salt-versions:
  salt.function:
    - name: test.version
    - tgt: '*'
    - require:
      - salt: everyone-answers
