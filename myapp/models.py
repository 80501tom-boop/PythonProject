from django.db import models

# Create your models here.

class Student(models.Model):
    name = models.CharField(max_length=100)
    age = models.IntegerField()

    def __str__(self):
        return self.name
class myapp_userprofile(models.Model):
    id = models.AutoField(primary_key=True)
    username = models.CharField(max_length=100)
    usersex = models.CharField(max_length=10)
    userschool = models.CharField(max_length=20)
    userinterest = models.TextField()
    userthought = models.TextField()
    class Meta:
        db_table = 'myapp_userprofile'  # 強制對應到 MySQL 內的 myapp_userprofile 資料表[cite: 1]

    def __str__(self):
        return self.username