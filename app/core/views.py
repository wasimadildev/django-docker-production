from django.shortcuts import render, redirect, get_object_or_404
from django.views.generic import ListView, CreateView, UpdateView, DeleteView
from django.urls import reverse_lazy
from django.contrib import messages

from .models import Task


class TaskListView(ListView):
    model = Task
    template_name = 'core/task_list.html'
    context_object_name = 'tasks'


class TaskCreateView(CreateView):
    model = Task
    fields = ['title']
    template_name = 'core/task_form.html'
    success_url = reverse_lazy('task_list')

    def form_valid(self, form):
        messages.success(self.request, 'Task created successfully!')
        return super().form_valid(form)


class TaskUpdateView(UpdateView):
    model = Task
    fields = ['title', 'completed']
    template_name = 'core/task_form.html'
    success_url = reverse_lazy('task_list')

    def form_valid(self, form):
        messages.success(self.request, 'Task updated successfully!')
        return super().form_valid(form)


class TaskDeleteView(DeleteView):
    model = Task
    template_name = 'core/task_confirm_delete.html'
    success_url = reverse_lazy('task_list')

    def form_valid(self, form):
        messages.success(self.request, 'Task deleted successfully!')
        return super().form_valid(form)


def toggle_task(request, pk):
    task = get_object_or_404(Task, pk=pk)
    task.completed = not task.completed
    task.save()
    messages.success(request, 'Task status updated!')
    return redirect('task_list')