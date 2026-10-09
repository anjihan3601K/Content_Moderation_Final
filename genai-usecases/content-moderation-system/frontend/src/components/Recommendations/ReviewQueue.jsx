import React, { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Container,
  Paper,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import {
  Refresh as RefreshIcon,
} from '@mui/icons-material';
import { recommendationAPI } from '../../services/api';

const formatLabel = (value) => String(value || '').replace(/_/g, ' ');

const percent = (value) => `${Math.round(value * 100)}%`;

const ReviewQueue = () => {
  const navigate = useNavigate();
  const [queue, setQueue] = useState(null);
  const [loading, setLoading] = useState(true);
  const [unavailable, setUnavailable] = useState(false);
  const [error, setError] = useState(null);

  const loadQueue = async () => {
    setLoading(true);
    setError(null);
    try {
      setQueue(await recommendationAPI.getQueue(50));
    } catch (err) {
      console.error('Error loading review queue:', err);
      if (err.response?.status === 404) {
        setUnavailable(true);
      } else {
        setError(err.response?.data?.detail || 'Failed to load the review queue');
      }
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadQueue();
  }, []);

  if (unavailable) {
    return (
      <Container maxWidth="md" sx={{ py: 4 }}>
        <Alert severity="info">The prioritized review queue is not enabled on this server.</Alert>
      </Container>
    );
  }

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* Header */}
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Box>
          <Typography variant="h4" component="h1" fontWeight="bold" gutterBottom>
            Priority Review Queue
          </Typography>
          <Typography variant="body1" color="text.secondary">
            Posts waiting for review, most urgent first: likely harm, how much the agents disagreed, and how many people have seen it
          </Typography>
        </Box>
        <Button variant="outlined" startIcon={<RefreshIcon />} onClick={loadQueue} disabled={loading}>
          Refresh
        </Button>
      </Box>

      {error && (
        <Alert severity="error" onClose={() => setError(null)} sx={{ mb: 3 }}>
          {error}
        </Alert>
      )}

      {queue && queue.escalated_withheld > 0 && (
        <Alert severity="warning" sx={{ mb: 3 }}>
          {queue.escalated_withheld} high-risk {queue.escalated_withheld === 1 ? 'post is' : 'posts are'} waiting for a senior moderator and not shown here.
        </Alert>
      )}

      <Paper>
        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
            <CircularProgress />
          </Box>
        ) : (
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableCell><strong>#</strong></TableCell>
                  <TableCell><strong>Content</strong></TableCell>
                  <TableCell><strong>Category</strong></TableCell>
                  <TableCell><strong>Status</strong></TableCell>
                  <TableCell align="right"><strong>Likely Harm</strong></TableCell>
                  <TableCell align="right"><strong>Uncertainty</strong></TableCell>
                  <TableCell align="right"><strong>Priority</strong></TableCell>
                  <TableCell><strong>Actions</strong></TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {(queue?.items || []).map((item, index) => (
                  <TableRow key={item.content_id} hover>
                    <TableCell>{index + 1}</TableCell>
                    <TableCell sx={{ maxWidth: 360 }}>
                      <Typography variant="body2" noWrap title={item.content_text}>
                        {item.content_text || item.content_id}
                      </Typography>
                      {item.is_escalated && <Chip label="High-risk category" color="error" size="small" sx={{ mt: 0.5 }} />}
                    </TableCell>
                    <TableCell sx={{ textTransform: 'capitalize' }}>{formatLabel(item.category)}</TableCell>
                    <TableCell sx={{ textTransform: 'capitalize' }}>{formatLabel(item.status)}</TableCell>
                    <TableCell align="right">{percent(item.expected_harm)}</TableCell>
                    <TableCell align="right">{percent(item.agent_disagreement)}</TableCell>
                    <TableCell align="right">{item.priority_score.toFixed(2)}</TableCell>
                    <TableCell>
                      <Button size="small" variant="contained" onClick={() => navigate(`/review/${item.content_id}`)}>
                        Review
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}

        {!loading && (queue?.items || []).length === 0 && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Typography variant="body1" color="text.secondary">
              Nothing is waiting for review
            </Typography>
          </Box>
        )}
      </Paper>
    </Container>
  );
};

export default ReviewQueue;
