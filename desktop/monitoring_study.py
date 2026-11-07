"""Reproducible nearest-centroid experiment on generated backup-change features."""
import random
from statistics import mean


def model_study():
    def sample(seed, count):
        rng = random.Random(seed)
        for index in range(count):
            suspicious = index % 2 == 1
            if suspicious:
                changed = rng.randint(12,85)
                deleted = rng.randint(0,15)
                added = rng.randint(0,12)
            else:
                changed = rng.randint(0,75) if index % 4 == 0 else rng.randint(0,20)
                deleted = rng.randint(0,4)
                added = rng.randint(10,45) if index % 4 == 0 else rng.randint(0,20)
            yield (changed/100,deleted/100,added/100), suspicious

    training = list(sample(2301,200))
    centroids = {label: tuple(mean(row[i] for row,y in training if y == label)
                              for i in range(3)) for label in (False,True)}
    def classify(row):
        return min(centroids,key=lambda label: sum((a-b)**2 for a,b in zip(row,centroids[label])))

    results = {'rule':dict(tp=0,tn=0,fp=0,fn=0),'model':dict(tp=0,tn=0,fp=0,fn=0)}
    for row,label in sample(2302,100):
        for name,prediction in [('rule',sum(row[:2]) >= .30),('model',classify(row))]:
            key = ('tp' if label else 'fp') if prediction else ('fn' if label else 'tn')
            results[name][key] += 1
    return {'method':'Supervised nearest centroid','training_examples':200,'test_examples':100,
            'features':['changed fraction','deleted fraction','added fraction'],
            'confusion_counts':results,'scope':'Generated features and labels from distinct seeded samples. Illustrates model evaluation; operational accuracy requires real labeled events.'}
