import numpy as np
import torch
import torch.nn as nn
from torch.autograd import Variable
import torch.nn.functional as F

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

# Implementation of Twin Delayed Deep Deterministic Policy Gradients (TD3)
# Paper: https://arxiv.org/abs/1802.09477

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

        # Q1 architecture
        self.l1 = nn.Linear(state_dim + action_dim, nn_dim[0])
        self.l2 = nn.Linear(nn_dim[0], nn_dim[1])
        self.l3 = nn.Linear(nn_dim[1], 1)

        # Q2 architecture
        self.l4 = nn.Linear(state_dim + action_dim, nn_dim[0])
        self.l5 = nn.Linear(nn_dim[0], nn_dim[1])
        self.l6 = nn.Linear(nn_dim[1], 1)


    def forward(self, x, u):
        xu = torch.cat([x, u], 1)

        x1 = F.relu(self.l1(xu))
        x1 = F.relu(self.l2(x1))
        x1 = self.l3(x1)

        x2 = F.relu(self.l4(xu))
        x2 = F.relu(self.l5(x2))
        x2 = self.l6(x2)
        return x1, x2


    def Q1(self, x, u):
        xu = torch.cat([x, u], 1)

        x1 = F.relu(self.l1(xu))
        x1 = F.relu(self.l2(x1))
        x1 = self.l3(x1)
        return x1


class TD3(object):

    def __init__(self, state_dim, action_dim, max_action, actor_dim=(40,30),
            critic_dim=(40,30),learning_rate=1e-4):

        self.actor = Actor(state_dim, action_dim, max_action, actor_dim).to(device)
        self.actor_target = Actor(state_dim, action_dim, max_action, actor_dim).to(device)
        self.actor_target.load_state_dict(self.actor.state_dict())
        self.actor_optimizer = torch.optim.Adam(self.actor.parameters(), lr=learning_rate)
        self.critic = Critic(state_dim, action_dim, critic_dim).to(device)
        self.critic_target = Critic(state_dim, action_dim, critic_dim).to(device)
        self.critic_target.load_state_dict(self.critic.state_dict())
        self.critic_optimizer = torch.optim.Adam(self.critic.parameters(), lr=learning_rate, weight_decay=1e-4)
        self.max_action = max_action
        self.state_dim = state_dim
        self.action_dim = action_dim

    def select_action(self, state):
        state = torch.FloatTensor(state.reshape((1, -1))).to(device)
        return self.actor(state).cpu().data.numpy().flatten()

    def train(self, replay_buffer, iterations, batch_size=100, discount=0.99, tau=0.005, policy_noise=0.2, noise_clip=0.5, policy_freq=2):

        for it in range(iterations):
            x, u, r, d, y = replay_buffer.uniform_sample(batch_size)

            state = torch.FloatTensor(x.reshape((batch_size, self.state_dim))).to(device)
            action = torch.FloatTensor(u.reshape((batch_size, self.action_dim))).to(device)
            next_state = torch.FloatTensor(y.reshape((batch_size, self.state_dim))).to(device)
            done = torch.FloatTensor(1 - d).to(device)
            reward = torch.FloatTensor(r).to(device)

            # Select action according to policy and add clipped noise
            noise = torch.FloatTensor(u).data.normal_(0, policy_noise).to(device)
            noise = noise.clamp(-noise_clip, noise_clip)
            next_action = (self.actor_target(next_state) + noise).clamp(-self.max_action, self.max_action)

            # Compute the target Q value
            target_Q1, target_Q2 = self.critic_target(next_state, next_action)
            target_Q = torch.min(target_Q1, target_Q2)
            target_Q = reward + (done * discount * target_Q).detach()

            # Get current Q estimates
            current_Q1, current_Q2 = self.critic(state, action)

            # Compute critic loss
            critic_loss = F.mse_loss(current_Q1, target_Q) + F.mse_loss(current_Q2, target_Q)

            # Optimize the critic
            self.critic_optimizer.zero_grad()
            critic_loss.backward()
            self.critic_optimizer.step()

            # Delayed policy updates
            if it % policy_freq == 0:

                    # Compute actor loss
                    actor_loss = -self.critic.Q1(state, self.actor(state)).mean()

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

            current_Q1,current_Q2 = self.critic(torch_state,torch_action)
            cpu_Q1 = np.asscalar(current_Q1.detach().cpu().numpy())
            cpu_Q2 = np.asscalar(current_Q2.detach().cpu().numpy())
            q_value = [min(cpu_Q1,cpu_Q2)]
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
