import numpy as np
import gym
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Implementation of Deep Deterministic Policy Gradients (DDPG)
# Paper: https://arxiv.org/abs/1509.02971
# [Not the implementation used in the TD3 paper]

class Actor(nn.Module):
    def __init__(self, state_dim, action_dim, max_action, nn_dim):
        super(Actor, self).__init__()

        self.l1 = nn.Linear(state_dim, nn_dim[0])
        self.l2 = nn.Linear(nn_dim[0], nn_dim[1])
        self.l3 = nn.Linear(nn_dim[1], action_dim)
        self.max_action = max_action


    def forward(self, x):
        x = F.relu(self.l1(x))
        x = F.relu(self.l2(x))
        x = self.max_action * torch.tanh(self.l3(x))
        return x


class Critic(nn.Module):
    def __init__(self, state_dim, action_dim, nn_dim):
        super(Critic, self).__init__()

        self.l1 = nn.Linear(state_dim, nn_dim[0])
        self.l2 = nn.Linear(nn_dim[0] + action_dim, nn_dim[1])
        self.l3 = nn.Linear(nn_dim[1], 1)


    def forward(self, x, u):
        x = F.relu(self.l1(x))
        x = F.relu(self.l2(torch.cat([x, u], 1)))
        x = self.l3(x)
        return x


class DDPG(object):
    def __init__(self, state_dim, action_dim, max_action, actor_dim=(40,30),
            critic_dim=(40,30), learning_rate=1e-4):
        self.actor = Actor(state_dim, action_dim, max_action, actor_dim).to(device)
        self.actor_target = Actor(state_dim, action_dim, max_action, actor_dim).to(device)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=learning_rate)
        self.critic = Critic(state_dim, action_dim, critic_dim).to(device)
        self.critic_target = Critic(state_dim, action_dim, critic_dim).to(device)
        self.critic_target.load_state_dict(self.critic.state_dict())
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters(), lr=learning_rate, weight_decay=1e-4)
        self.state_dim = state_dim
        self.action_dim = action_dim

    def select_action(self, state):
        state = torch.FloatTensor(state.reshape(1, -1)).to(device)
        return self.actor(state).cpu().data.numpy().flatten()


    def train(self, replay_buffer, iterations, batch_size=64, discount=0.99, tau=0.001):
        for it in range(iterations):
            x, u, r, d, y = replay_buffer.uniform_sample(batch_size)

            state = torch.FloatTensor(x.reshape((batch_size, self.state_dim))).to(device)
            action = torch.FloatTensor(u.reshape((batch_size, self.action_dim))).to(device)
            next_state = torch.FloatTensor(y.reshape((batch_size, self.state_dim))).to(device)
            done = torch.FloatTensor(1 - d).to(device)
            reward = torch.FloatTensor(r).to(device)

            # Compute the target Q value
            target_Q = self.critic_target(next_state, self.actor_target(next_state))
            target_Q = reward + (done * discount * target_Q).detach()

            # Get current Q estimate
            current_Q = self.critic(state, action)

            # Compute critic loss
            critic_loss = F.mse_loss(current_Q, target_Q)

            # Optimize the critic
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            self.critic_optimizer.step()

            # Compute actor loss
            actor_loss = -self.critic(state, self.actor(state)).mean()

            # Optimize the actor 
            self.actor_optimizer.zero_grad()
            actor_loss.backward()
            self.actor_optimizer.step()

            # Update the frozen target models
            for param, target_param in zip(self.critic.parameters(), self.critic_target.parameters()):
                    target_param.data.copy_(tau * param.data + (1 - tau) * target_param.data)

            for param, target_param in zip(self.actor.parameters(), self.actor_target.parameters()):
                    target_param.data.copy_(tau * param.data + (1 - tau) * target_param.data)


    def save(self, filename, directory):
        torch.save(self.actor.state_dict(), '%s/%s_actor.pth' % (directory, filename))
        torch.save(self.critic.state_dict(), '%s/%s_critic.pth' % (directory, filename))


    def load(self, filename, directory):
        self.actor.load_state_dict(torch.load('%s/%s_actor.pth' % (directory, filename), map_location=device))
        self.critic.load_state_dict(torch.load('%s/%s_critic.pth' % (directory, filename), map_location=device))


    def get_Q_values(self,env,size):

        dim_linspaces = []
        for dim in range(env.observation_space.high.shape[0]):
            dim_linspaces.append(np.linspace(
                    -env.observation_space.high[dim],
                    env.observation_space.high[dim],
                    size))
        meshed_dim = np.meshgrid(*dim_linspaces)
        reshaped_meshed_dim = []
        for dim in meshed_dim:
            reshaped_meshed_dim.append(dim.ravel().reshape(-1,1))
        grid = np.hstack(reshaped_meshed_dim)

        Q_values = []
        for state in grid :

            torch_state = torch.FloatTensor(state.reshape((1,self.state_dim))).to(device)
            torch_action = self.actor(torch_state)

            current_Q = self.critic(torch_state,torch_action)
            cpu_Q = np.asscalar(current_Q.detach().cpu().numpy())
            q_value = [cpu_Q]
            q_value.extend(state)
            action = torch_action.detach().cpu().numpy()
            Q_values.append(q_value)

        return np.array(Q_values)
    

    def get_Pi_values(self,env,size):

        dim_linspaces = []
        for dim in range(env.observation_space.high.shape[0]):
            dim_linspaces.append(np.linspace(
                    -env.observation_space.high[dim],
                    env.observation_space.high[dim],
                    size))
        meshed_dim = np.meshgrid(*dim_linspaces)
        reshaped_meshed_dim = []
        for dim in meshed_dim:
            reshaped_meshed_dim.append(dim.ravel().reshape(-1,1))
        grid = np.hstack(reshaped_meshed_dim)

        Pi_values = []
        for state in grid :

            torch_state = torch.FloatTensor(state.reshape((1,self.state_dim))).to(device)
            torch_action = self.actor(torch_state)
            pi_value = state.flatten().tolist()
            action = torch_action.detach().cpu().numpy()
            pi_value.extend(action.flatten().tolist())
            Pi_values.append(pi_value)

        return np.array(Pi_values)
